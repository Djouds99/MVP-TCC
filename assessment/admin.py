"""Admin para inspecionar as sessoes e respostas coletadas."""

from django.contrib import admin, messages

from assessment.models import (
    AssessmentSession,
    InstrumentResponse,
    InstrumentSession,
    QuestionResponse,
    StudyPhase,
    StudySettings,
)
from students.models import Student, StudyGroup


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
    Onde o professor vira a etapa de cada turma.

    As duas turmas aparecem lado a lado na mesma lista, com a etapa editavel ali
    mesmo, junto de quantos alunos de cada turma ja concluiram cada prova. E a
    mitigacao do risco que etapas independentes trazem: avancar uma turma e
    esquecer da outra, ou avancar antes de a turma terminar a prova
    (CLAUDE.md secao 11).
    """

    list_display = (
        "group",
        "stage",
        "pre_test_done",
        "post_test_done",
        "updated_at",
    )
    list_display_links = None
    list_editable = ("stage",)

    def has_add_permission(self, request):
        # As duas linhas vem da migracao; uma terceira nao teria turma a que
        # pertencer.
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description="pré-teste concluído")
    def pre_test_done(self, obj):
        return self._completion(obj, StudyPhase.PRE)

    @admin.display(description="pós-teste concluído")
    def post_test_done(self, obj):
        return self._completion(obj, StudyPhase.POST)

    @staticmethod
    def _completion(obj, phase) -> str:
        total = Student.objects.filter(group=obj.group).count()
        done = InstrumentSession.objects.filter(
            student__group=obj.group, phase=phase, finished_at__isnull=False
        ).count()
        return f"{done} de {total} alunos"

    def changelist_view(self, request, extra_context=None):
        # So no GET: no POST a mensagem seria calculada com a etapa de antes de
        # salvar e apareceria desatualizada depois do redirecionamento.
        if request.method == "GET":
            rows = {row.group: row for row in StudySettings.objects.all()}
            pilot = rows.get(StudyGroup.PILOT)
            control = rows.get(StudyGroup.CONTROL)
            if pilot and control and pilot.stage != control.stage:
                self.message_user(
                    request,
                    "As turmas estão em etapas diferentes — piloto: "
                    f"{pilot.get_stage_display()}; controle: "
                    f"{control.get_stage_display()}. Isso é permitido, mas "
                    "confira se é intencional antes de liberar os alunos.",
                    level=messages.WARNING,
                )
        return super().changelist_view(request, extra_context=extra_context)


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
