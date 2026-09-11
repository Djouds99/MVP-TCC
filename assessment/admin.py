"""Admin para inspecionar as sessoes e respostas coletadas."""

from django.contrib import admin

from assessment.models import (
    AssessmentSession,
    InstrumentResponse,
    InstrumentSession,
    QuestionResponse,
    StudySettings,
)


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


class InstrumentResponseInline(admin.TabularInline):
    model = InstrumentResponse
    extra = 0
    readonly_fields = ("question", "chosen_index", "is_correct", "answered_at")
    can_delete = False


@admin.register(StudySettings)
class StudySettingsAdmin(admin.ModelAdmin):
    """
    Onde o professor vira a chave entre pre-teste, atividade e pos-teste.

    E a unica configuracao do estudo que muda durante a aplicacao.
    """

    list_display = ("stage", "updated_at")

    def has_add_permission(self, request):
        # Linha unica: o registro e criado sozinho no primeiro acesso.
        return not StudySettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(InstrumentSession)
class InstrumentSessionAdmin(admin.ModelAdmin):
    list_display = ("student", "phase", "score", "finished_at")
    list_filter = ("phase", "student__group", "finished_at")
    search_fields = ("student__code",)
    readonly_fields = ("started_at", "finished_at", "curriculum_release")
    inlines = [InstrumentResponseInline]

    @admin.display(description="acertos")
    def score(self, obj):
        return obj.score
