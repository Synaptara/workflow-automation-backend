import logging
import re
import time

from asgiref.sync import async_to_sync
from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded
from channels.layers import get_channel_layer
from django.db.models import F
from django.utils import timezone

from . import executors  # noqa: F401
from .condition import _resolve, evaluate_condition
from .executors import EXECUTOR_REGISTRY
from .executors.trello import poll_trello_new_cards
from .models import (
    Credential,
    Notification,
    StepRun,
    TaskUsage,
    TriggerState,
    Workflow,
    WorkflowRun,
    WorkflowStep,
)

logger = logging.getLogger(__name__)

POLLING_HANDLERS = {
    "trello_new_card": poll_trello_new_cards,
}

NON_RETRYABLE_PATTERNS = (
    "401",
    "403",
    "404",
    "400",
    "missing permissions",
    "50013",
    "vault",
    "re-authenticate",
    "not connected",
    "expired",
    "unsupported",
    "invalid json",
    "blocked",
)


def _is_non_retryable(exc: Exception) -> bool:
    """Returns True if the error is a permanent configuration or auth issue that should not be retried."""
    if isinstance(exc, ValueError):
        return True
    msg = str(exc).lower()
    return any(pat in msg for pat in NON_RETRYABLE_PATTERNS)


def _is_auth_failure(msg: str) -> bool:
    lowered = msg.lower()
    return any(
        term in lowered
        for term in (
            "vault",
            "re-authenticate",
            "expired",
            "401",
            "unauthorized",
            "not connected",
            "50013",
            "missing permissions",
        )
    )


def _emit(run_id, user_id, event, data):
    layer = get_channel_layer()
    if layer is None:
        return

    async_to_sync(layer.group_send)(
        f"run_{run_id}",
        {"type": "run.event", "event": event, "data": data},
    )

    async_to_sync(layer.group_send)(
        f"user_{user_id}",
        {"type": "notify.event", "event": event, "data": data},
    )


def inject_variables(config, context):
    if isinstance(config, dict):
        return {k: inject_variables(v, context) for k, v in config.items()}
    elif isinstance(config, list):
        return [inject_variables(i, context) for i in config]
    elif isinstance(config, str):

        def replacer(match):
            path = match.group(1).strip()
            val = _resolve(path, context)
            return str(val) if val not in (None, "") else ""

        return re.sub(r"\{\{\s*([^}]+)\s*\}\}", replacer, config)
    return config


def _run_action_step(run, step, context, max_attempts=3):
    step_run = StepRun.objects.create(run=run, step=step, status="running")
    _emit(
        run.id,
        run.workflow.owner.id,
        "step_started",
        {"step_id": str(step.id), "action_key": step.action_key},
    )

    executor = EXECUTOR_REGISTRY.get(step.action_key)
    if not executor:
        raise RuntimeError(f"Executor {step.action_key} not found in registry.")

    last_exc = None
    clean_step_config = {k: v for k, v in (step.config or {}).items() if v != ""}

    try:
        cred = Credential.objects.get(owner=run.workflow.owner, service=step.action_key)
        vault_data = cred.data if isinstance(cred.data, dict) else {}
        merged_config = {**vault_data, **clean_step_config}
    except Credential.DoesNotExist:
        merged_config = clean_step_config

    dynamic_config = inject_variables(merged_config, context)

    for attempt in range(1, max_attempts + 1):
        try:
            output = executor.execute(step.app_event, dynamic_config, context)

            step_run.status = "success"
            step_run.output = (
                output if isinstance(output, dict) else {"result": str(output)}
            )
            step_run.finished_at = timezone.now()
            step_run.save()

            if step.client_id:
                context[step.client_id] = step_run.output

            TaskUsage.objects.filter(user=run.workflow.owner).update(
                count=F("count") + 1
            )

            _emit(
                run.id,
                run.workflow.owner.id,
                "step_finished",
                {
                    "step_id": str(step.id),
                    "status": "success",
                    "output": step_run.output,
                },
            )
            return
        except Exception as exc:
            last_exc = exc
            if _is_non_retryable(exc):
                logger.warning(
                    "Step %s failed with non-retryable error: %s", step.id, exc
                )
                break
            logger.warning(
                "Step %s attempt %d/%d failed: %s", step.id, attempt, max_attempts, exc
            )
            if attempt < max_attempts:
                time.sleep(2 ** (attempt - 1))

    step_run.status = "failed"
    step_run.error = str(last_exc)
    step_run.finished_at = timezone.now()
    step_run.save()
    _emit(
        run.id,
        run.workflow.owner.id,
        "step_finished",
        {"step_id": str(step.id), "status": "failed", "error": str(last_exc)},
    )
    raise RuntimeError(str(last_exc))


def _walk(run, step, context):
    if step.step_type == "condition":
        step_run = StepRun.objects.create(run=run, step=step, status="running")
        try:
            dynamic_config = inject_variables(step.config, context)
            result = evaluate_condition(dynamic_config, context)
            branch = "true" if result else "false"

            step_run.status = "success"
            step_run.output = {"evaluated_true": result, "branch_taken": branch}
            step_run.finished_at = timezone.now()
            step_run.save()

            _emit(
                run.id,
                run.workflow.owner.id,
                "condition_evaluated",
                {"step_id": str(step.id), "result": result},
            )
            children = step.children.filter(branch=branch).order_by("order")
        except Exception as exc:
            step_run.status = "failed"
            step_run.error = str(exc)
            step_run.finished_at = timezone.now()
            step_run.save()
            raise RuntimeError(f"Condition evaluation failed: {exc}")
    else:
        if step.step_type == "action":
            _run_action_step(run, step, context)
        children = step.children.order_by("order")

    for child in children:
        _walk(run, child, context)


@shared_task(bind=True, max_retries=2, soft_time_limit=120)
def run_workflow(self, run_id):
    run = WorkflowRun.objects.select_related("workflow", "workflow__owner").get(
        id=run_id
    )
    owner = run.workflow.owner

    usage, _ = TaskUsage.objects.get_or_create(user=owner)
    if usage.limit > 0 and usage.count >= usage.limit:
        run.status = "failed"
        run.finished_at = timezone.now()
        run.save(update_fields=["status", "finished_at"])
        notif = Notification.objects.create(
            user=owner,
            type="usage_warning",
            title="Monthly task limit reached",
            body=f"{run.workflow.name} was skipped because you reached {usage.count}/{usage.limit} tasks.",
            link="/billing",
            data={"run_id": str(run.id), "workflow_id": str(run.workflow.id)},
        )
        _emit(run.id, owner.id, "notification_created", {"id": str(notif.id)})
        _emit(run.id, owner.id, "run_finished", {"status": "failed"})
        return

    run.status = "running"
    run.save(update_fields=["status"])
    _emit(run.id, owner.id, "run_started", {})

    context = {"trigger": run.trigger_payload}
    root_steps = run.workflow.steps.filter(
        step_type="trigger", parent__isnull=True
    ).order_by("order")

    last_error_message = ""

    try:
        for trigger_step in root_steps:
            for child in trigger_step.children.order_by("order"):
                _walk(run, child, context)
        run.status = "success"
    except SoftTimeLimitExceeded:
        run.status = "failed"
        last_error_message = "Workflow timed out after 120 seconds."
        logger.error("Workflow run %s timed out after 120 seconds", run_id)
    except Exception as exc:
        run.status = "failed"
        last_error_message = str(exc)
        logger.error("Workflow run %s failed: %s", run_id, str(exc))
    finally:
        run.finished_at = timezone.now()
        run.save(update_fields=["status", "finished_at"])

        workflow_name = run.workflow.name or "Workflow"
        if run.status == "failed":
            is_auth_err = _is_auth_failure(last_error_message)
            notif = Notification.objects.create(
                user=owner,
                type="integration_error" if is_auth_err else "run_failed",
                title=(
                    f"{workflow_name}: Connection required"
                    if is_auth_err
                    else f"{workflow_name} failed"
                ),
                body=last_error_message[:200],
                link="/integrations" if is_auth_err else "/history",
                data={"run_id": str(run.id), "workflow_id": str(run.workflow.id)},
            )
            _emit(
                run.id,
                owner.id,
                "notification_created",
                {"id": str(notif.id)},
            )

        elif run.status == "success":
            notif = Notification.objects.create(
                user=owner,
                type="run_success",
                title=f"{workflow_name} completed",
                body="All steps executed successfully.",
                link="/history",
                data={"run_id": str(run.id), "workflow_id": str(run.workflow.id)},
            )
            _emit(
                run.id,
                owner.id,
                "notification_created",
                {"id": str(notif.id)},
            )

        _emit(run.id, owner.id, "run_finished", {"status": run.status})


@shared_task
def trigger_scheduled_workflow(workflow_id):
    """Fired autonomously by Celery Beat based on the user's schedule."""
    try:
        workflow = Workflow.objects.select_related("owner").get(
            id=workflow_id, is_active=True
        )
        usage = TaskUsage.objects.filter(user=workflow.owner).first()
        if usage and usage.limit > 0 and usage.count >= usage.limit:
            return
        run = WorkflowRun.objects.create(
            workflow=workflow, trigger_payload={"source": "schedule"}
        )
        run_workflow.delay(str(run.id))
    except Workflow.DoesNotExist:
        pass


@shared_task
def poll_external_triggers():
    """
    Scheduled via Celery Beat (e.g., every 60 seconds).
    Checks active polling workflows and dispatches runs for new items.
    """
    polling_workflows = (
        Workflow.objects.filter(
            is_active=True,
            steps__step_type="trigger",
            steps__parent__isnull=True,
            steps__action_key__in=POLLING_HANDLERS.keys(),
        )
        .select_related("owner")
        .distinct()
    )

    for workflow in polling_workflows:
        usage = TaskUsage.objects.filter(user=workflow.owner).first()
        if usage and usage.limit > 0 and usage.count >= usage.limit:
            continue

        trigger_step = workflow.steps.filter(
            step_type="trigger", parent__isnull=True
        ).first()
        if not trigger_step:
            continue

        handler = POLLING_HANDLERS.get(trigger_step.action_key)
        if not handler:
            continue

        state, _ = TriggerState.objects.get_or_create(workflow=workflow)

        try:
            new_items, updated_last_seen = handler(
                trigger_step.config, state.last_seen_id
            )

            if updated_last_seen != state.last_seen_id:
                state.last_seen_id = updated_last_seen
                state.save(update_fields=["last_seen_id", "last_checked_at"])

            for item in new_items:
                run = WorkflowRun.objects.create(
                    workflow=workflow,
                    trigger_payload=item,
                )
                run_workflow.delay(str(run.id))

        except Exception as exc:
            logger.error("Polling failed for workflow %s: %s", workflow.id, exc)


@shared_task
def route_ingested_event(source, payload):
    """
    Asynchronous event router for high-volume platform webhooks and ingress listeners.
    """
    event_type = payload.get("event_type", "new_message")

    trigger_steps = WorkflowStep.objects.filter(
        workflow__is_active=True,
        parent__isnull=True,
        step_type="trigger",
        action_key=source,
    ).select_related("workflow", "workflow__owner")

    for step in trigger_steps:
        config = step.config or {}

        executor = EXECUTOR_REGISTRY.get(source)
        if executor and hasattr(executor, "match_ingress_event"):
            if not executor.match_ingress_event(
                step.app_event, event_type, payload, config
            ):
                continue

        usage = TaskUsage.objects.filter(user=step.workflow.owner).first()
        if usage and usage.limit > 0 and usage.count >= usage.limit:
            logger.warning(
                "Execution rejected for workflow %s: User '%s' quota exceeded (%d/%d).",
                step.workflow.id,
                step.workflow.owner.username,
                usage.count,
                usage.limit,
            )
            continue

        run = WorkflowRun.objects.create(
            workflow=step.workflow,
            trigger_payload=payload,
        )
        run_workflow.delay(str(run.id))
