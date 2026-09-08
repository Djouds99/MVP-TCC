"""Admin para inspecionar as sessoes e respostas coletadas."""

from django.contrib import admin

from assessment.models import AssessmentSession, QuestionResponse


class QuestionResponseInline(admin.TabularInline):
    model = QuestionResponse
    extra = 0
    readonly_fields = ("question", "chosen_index", "is_correct", "position", "answered_at")
    can_delete = False


@admin.register(AssessmentSession)
class AssessmentSessionAdmin(admin.ModelAdmin):
    list_display = (
        "student",
        "goal_item",
        "question_count",
        "resulting_state",
        "started_at",
        "finished_at",
    )
    list_filter = ("student__group", "finished_at")
    search_fields = ("student__code",)
    readonly_fields = ("started_at", "finished_at", "curriculum_release")
    inlines = [QuestionResponseInline]


@admin.register(QuestionResponse)
class QuestionResponseAdmin(admin.ModelAdmin):
    list_display = ("session", "position", "question", "is_correct", "answered_at")
    list_filter = ("is_correct", "session__student__group")
    search_fields = ("session__student__code", "question__code")
