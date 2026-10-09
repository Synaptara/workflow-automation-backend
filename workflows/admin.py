from django.contrib import admin

from .models import (
    Announcement,
    Credential,
    Notification,
    StepRun,
    Workflow,
    WorkflowRun,
    WorkflowStep,
)

admin.site.register(Notification)
admin.site.register(Announcement)

admin.site.register(Workflow)
admin.site.register(WorkflowStep)
admin.site.register(WorkflowRun)
admin.site.register(StepRun)
admin.site.register(Credential)
