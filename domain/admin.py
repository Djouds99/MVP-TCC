"""
Admin usado para inspecao dos dados, nao para edicao de conteudo.

Topicos, itens e estados vem do arquivo versionado e sao regravados a cada
`load_curriculum` — editar por aqui seria perdido no proximo carregamento, entao
ficam somente leitura de proposito (CLAUDE.md secao 5).
"""

from django.contrib import admin

from domain.models import (
    CurriculumRelease,
    KnowledgeItem,
    KnowledgeState,
    Question,
    Topic,
)


class ReadOnlyAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Topic)
class TopicAdmin(ReadOnlyAdmin):
    list_display = ("position", "code", "name", "prerequisite_codes", "item_count")
    ordering = ("position",)

    @admin.display(description="pre-requisitos")
    def prerequisite_codes(self, obj):
        return ", ".join(obj.prerequisites.values_list("code", flat=True)) or "—"

    @admin.display(description="itens")
    def item_count(self, obj):
        return obj.items.count()


@admin.register(KnowledgeItem)
class KnowledgeItemAdmin(ReadOnlyAdmin):
    list_display = ("code", "name", "topic", "difficulty", "prerequisite_count")
    list_filter = ("topic", "difficulty")
    search_fields = ("code", "name")

    @admin.display(description="pre-requisitos (fecho)")
    def prerequisite_count(self, obj):
        return obj.prerequisites.count()


@admin.register(Question)
class QuestionAdmin(ReadOnlyAdmin):
    list_display = ("code", "item", "difficulty", "alternative_count")
    list_filter = ("item__topic", "difficulty")
    search_fields = ("code", "statement")

    @admin.display(description="alternativas")
    def alternative_count(self, obj):
        return len(obj.alternatives)


@admin.register(KnowledgeState)
class KnowledgeStateAdmin(ReadOnlyAdmin):
    list_display = ("__str__", "size")
    list_filter = ("size",)
    search_fields = ("signature",)


@admin.register(CurriculumRelease)
class CurriculumReleaseAdmin(ReadOnlyAdmin):
    list_display = ("version", "checksum", "loaded_at", "item_count", "state_count")
