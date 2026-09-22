import logging
import time

from celery import shared_task
from django.utils import timezone
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

from .models import WorkflowRun, StepRun
from .condition import evaluate_condition
from . import executors  # noqa: F401 — import triggers @register decorators (slack, trello)
from .executors import EXECUTOR_REGISTRY

logger = logging.getLogger(__name__)


def _emit(run_id, event, data):
    layer = get_channel_layer()
    if layer is None:
        return
    async_to_sync(layer.group_send)(
        f"run_{run_id}",
        {"type": "run.event", "event": event, "data": data},
    )


def _run_action_step(run, step, context, max_attempts=3):
    step_run = StepRun.objects.create(run=run, step=step, status="running")
    _emit(run.id, "step_started", {"step_id": str(step.id), "action_key": step.action_key})

    executor = EXECUTOR_REGISTRY[step.action_key]
    last_exc = None

    for attempt in range(1, max_attempts + 1):
        try:
            output = executor.execute(step.config, context)
            step_run.status = "success"
            step_run.output = output
            step_run.finished_at = timezone.now()
            step_run.save()
            _emit(run.id, "step_finished", {"step_id": str(step.id), "status": "success", "output": output})
            return
        except Exception as exc:
            last_exc = exc
            logger.warning("Step %s attempt %d/%d failed: %s", step.id, attempt, max_attempts, exc)
            if attempt < max_attempts:
                time.sleep(2 ** (attempt - 1))  # 1s, 2s

    step_run.status = "failed"
    step_run.error = str(last_exc)
    step_run.finished_at = timezone.now()
    step_run.save()
    _emit(run.id, "step_finished", {"step_id": str(step.id), "status": "failed", "error": str(last_exc)})
    raise last_exc


def _walk(run, step, context):
    if step.step_type == "condition":
        result = evaluate_condition(step.config, context)
        branch = "true" if result else "false"
        _emit(run.id, "condition_evaluated", {"step_id": str(step.id), "result": result})
        children = step.children.filter(branch=branch).order_by("order")
    else:
        if step.step_type == "action":
            _run_action_step(run, step, context)
        children = step.children.order_by("order")

    for child in children:
        _walk(run, child, context)


@shared_task(bind=True, max_retries=2)
def run_workflow(self, run_id):
    run = WorkflowRun.objects.select_related("workflow").get(id=run_id)
    run.status = "running"
    run.save(update_fields=["status"])
    _emit(run.id, "run_started", {})

    context = run.trigger_payload
    root_steps = run.workflow.steps.filter(step_type="trigger", parent__isnull=True).order_by("order")

    try:
        for trigger_step in root_steps:
            for child in trigger_step.children.order_by("order"):
                _walk(run, child, context)
        run.status = "success"
    except Exception:
        run.status = "failed"
        logger.exception("Workflow run %s failed", run_id)
    finally:
        run.finished_at = timezone.now()
        run.save()
        _emit(run.id, "run_finished", {"status": run.status})
