import logging
import time
import re

from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded
from django.utils import timezone
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

from .models import WorkflowRun, StepRun
from .condition import evaluate_condition, _resolve
from . import executors  # noqa: F401
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

def inject_variables(config, context):
    if isinstance(config, dict):
        return {k: inject_variables(v, context) for k, v in config.items()}
    elif isinstance(config, list):
        return [inject_variables(i, context) for i in config]
    elif isinstance(config, str):
        def replacer(match):
            path = match.group(1).strip()
            val = _resolve(path, context)
            # HARDENED: Do not inject literal "None" strings if key is missing
            return str(val) if val not in (None, "") else ""
            
        return re.sub(r"\{\{\s*([^}]+)\s*\}\}", replacer, config)
    return config

def _run_action_step(run, step, context, max_attempts=3):
    step_run = StepRun.objects.create(run=run, step=step, status="running")
    _emit(run.id, "step_started", {"step_id": str(step.id), "action_key": step.action_key})

    executor = EXECUTOR_REGISTRY.get(step.action_key)
    last_exc = None

    dynamic_config = inject_variables(step.config, context)

    for attempt in range(1, max_attempts + 1):
        try:
            output = executor.execute(dynamic_config, context)
            step_run.status = "success"
            step_run.output = output if isinstance(output, dict) else {"result": str(output)}
            step_run.finished_at = timezone.now()
            step_run.save()
            
            if step.client_id:
                context[step.client_id] = step_run.output
                
            _emit(run.id, "step_finished", {"step_id": str(step.id), "status": "success", "output": step_run.output})
            return
        except Exception as exc:
            last_exc = exc
            logger.warning("Step %s attempt %d/%d failed: %s", step.id, attempt, max_attempts, exc)
            if attempt < max_attempts:
                time.sleep(2 ** (attempt - 1))

    step_run.status = "failed"
    step_run.error = str(last_exc)
    step_run.finished_at = timezone.now()
    step_run.save()
    _emit(run.id, "step_finished", {"step_id": str(step.id), "status": "failed", "error": str(last_exc)})
    raise RuntimeError(f"Step {step.id} failed after {max_attempts} attempts: {last_exc}")

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
            
            _emit(run.id, "condition_evaluated", {"step_id": str(step.id), "result": result})
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

# HARDENED: 120 second strict execution cutoff prevents hanging queues
@shared_task(bind=True, max_retries=2, soft_time_limit=120)
def run_workflow(self, run_id):
    run = WorkflowRun.objects.select_related("workflow").get(id=run_id)
    run.status = "running"
    run.save(update_fields=["status"])
    _emit(run.id, "run_started", {})

    context = {"trigger": run.trigger_payload}
    root_steps = run.workflow.steps.filter(step_type="trigger", parent__isnull=True).order_by("order")

    try:
        for trigger_step in root_steps:
            for child in trigger_step.children.order_by("order"):
                _walk(run, child, context)
        run.status = "success"
    except SoftTimeLimitExceeded:
        run.status = "failed"
        logger.error("Workflow run %s timed out after 120 seconds", run_id)
    except Exception as exc:
        run.status = "failed"
        logger.error("Workflow run %s failed: %s", run_id, str(exc))
    finally:
        run.finished_at = timezone.now()
        run.save(update_fields=["status", "finished_at"])
        _emit(run.id, "run_finished", {"status": run.status})

@shared_task
def trigger_scheduled_workflow(workflow_id):
    """Fired autonomously by Celery Beat based on the user's schedule."""
    from .models import Workflow
    try:
        workflow = Workflow.objects.get(id=workflow_id, is_active=True)
        # Create a run with a placeholder payload so {{trigger.source}} resolves
        run = WorkflowRun.objects.create(
            workflow=workflow, 
            trigger_payload={"source": "schedule"}
        )
        # Kick off the main execution engine
        run_workflow.delay(str(run.id))
    except Workflow.DoesNotExist:
        pass