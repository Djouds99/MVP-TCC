"""
Admin dos codigos de acesso.

Serve para o professor conferir e exportar os codigos gerados. Nao ha campo de
nome ou identificacao pessoal para preencher, e isso e proposital.
"""

from django.contrib import admin

from students.models import Student


@admin.register(Student)
class StudentAdmin(admin.ModelAdmin):
    list_display = ("code", "group", "created_at")
    list_filter = ("group",)
    search_fields = ("code",)
    readonly_fields = ("created_at",)
