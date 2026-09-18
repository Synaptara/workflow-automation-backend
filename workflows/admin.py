from django.contrib import admin
from .models import Workflow, WorkflowStep, WorkflowRun, StepRun, Credential

admin.site.register(Workflow)
admin.site.register(WorkflowStep)
admin.site.register(WorkflowRun)
admin.site.register(StepRun)
admin.site.register(Credential)
