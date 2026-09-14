"""
Etapa do estudo passa de linha unica global para uma linha por turma.

A linha que existia vira a da turma piloto, e a turma controle nasce com a mesma
etapa — ninguem muda de etapa por causa da migracao. Banco novo recebe as duas
linhas ja no pre-teste. Reversivel: volta a uma linha so, com a etapa da piloto.
"""

from django.db import migrations, models

GROUP_CHOICES = [
    ("pilot", "Piloto (usa o aplicativo)"),
    ("control", "Controle (nao usa o aplicativo)"),
]


def split_singleton(apps, schema_editor):
    StudySettings = apps.get_model("assessment", "StudySettings")
    rows = list(StudySettings.objects.order_by("pk"))
    stage = rows[0].stage if rows else "pre_test"

    # A linha unica era garantida so pelo `save()` do modelo; qualquer extra
    # criada por fora sairia sem turma e impediria o campo de virar obrigatorio.
    for extra in rows[1:]:
        extra.delete()
    if rows:
        rows[0].group = "pilot"
        rows[0].save(update_fields=["group"])

    for group, _label in GROUP_CHOICES:
        StudySettings.objects.get_or_create(group=group, defaults={"stage": stage})


def merge_back(apps, schema_editor):
    StudySettings = apps.get_model("assessment", "StudySettings")
    source = (
        StudySettings.objects.filter(group="pilot").first()
        or StudySettings.objects.order_by("pk").first()
    )
    stage = source.stage if source else "pre_test"
    StudySettings.objects.all().delete()
    StudySettings.objects.create(pk=1, stage=stage)


class Migration(migrations.Migration):
    dependencies = [
        ("assessment", "0002_studysettings_instrumentsession_instrumentresponse_and_more"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="studysettings",
            options={
                "ordering": ["group"],
                "verbose_name": "etapa da turma",
                "verbose_name_plural": "etapas das turmas",
            },
        ),
        migrations.AddField(
            model_name="studysettings",
            name="group",
            field=models.CharField(choices=GROUP_CHOICES, max_length=10, null=True),
        ),
        migrations.RunPython(split_singleton, merge_back),
        migrations.AlterField(
            model_name="studysettings",
            name="group",
            field=models.CharField(choices=GROUP_CHOICES, max_length=10, unique=True),
        ),
    ]
