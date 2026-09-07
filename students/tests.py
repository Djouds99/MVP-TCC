"""
Testes da identificacao do participante.

O que precisa estar certo aqui: o codigo e gerado dentro do alfabeto e do
comprimento acordados, nao colide, e o modelo nao guarda nada que identifique a
pessoa.
"""

from io import StringIO

from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError
from django.test import TestCase

from students.codes import (
    CODE_ALPHABET,
    DEFAULT_CODE_LENGTH,
    generate_code,
    normalize_code,
)
from students.models import Student, StudyGroup


class CodeGenerationTests(TestCase):
    def test_uses_only_the_allowed_alphabet(self):
        for _ in range(200):
            self.assertTrue(set(generate_code()) <= set(CODE_ALPHABET))

    def test_alphabet_excludes_look_alike_characters(self):
        for char in "O0I1":
            self.assertNotIn(char, CODE_ALPHABET)

    def test_respects_requested_length(self):
        for length in (4, 5, 6):
            self.assertEqual(len(generate_code(length)), length)

    def test_rejects_length_outside_range(self):
        for length in (3, 7):
            with self.assertRaises(ValueError):
                generate_code(length)

    def test_normalize_strips_noise_and_uppercases(self):
        self.assertEqual(normalize_code(" ab-3 4d "), "AB34D")

    def test_normalize_does_not_invent_a_valid_code(self):
        # "O" e "1" nao existem no alfabeto; devem continuar invalidos em vez de
        # serem convertidos em outro codigo qualquer.
        normalized = normalize_code("ao1bc")
        self.assertFalse(set(normalized) <= set(CODE_ALPHABET))


class StudentModelTests(TestCase):
    def test_stores_no_personal_field(self):
        field_names = {field.name for field in Student._meta.get_fields()}
        self.assertEqual(field_names, {"id", "code", "group", "created_at"})

    def test_code_is_unique(self):
        Student.objects.create(code="ABCD2", group=StudyGroup.PILOT)
        with self.assertRaises(IntegrityError):
            Student.objects.create(code="ABCD2", group=StudyGroup.CONTROL)

    def test_validation_rejects_characters_outside_alphabet(self):
        student = Student(code="ABC0I", group=StudyGroup.PILOT)
        with self.assertRaises(ValidationError):
            student.full_clean()

    def test_validation_rejects_wrong_length(self):
        for code in ("AB2", "ABCDEF2"):
            with self.assertRaises(ValidationError):
                Student(code=code, group=StudyGroup.PILOT).full_clean()

    def test_generated_students_do_not_collide(self):
        created = [
            Student.create_with_generated_code(group=StudyGroup.PILOT)
            for _ in range(60)
        ]
        self.assertEqual(len({student.code for student in created}), 60)
        for student in created:
            self.assertEqual(len(student.code), DEFAULT_CODE_LENGTH)


class CreateStudentsCommandTests(TestCase):
    def test_creates_the_requested_number_in_the_right_group(self):
        out = StringIO()
        call_command("create_students", group="pilot", count=5, stdout=out)

        self.assertEqual(Student.objects.filter(group=StudyGroup.PILOT).count(), 5)
        for student in Student.objects.all():
            self.assertIn(student.code, out.getvalue())

    def test_groups_are_independent(self):
        call_command("create_students", group="pilot", count=3, stdout=StringIO())
        call_command("create_students", group="control", count=4, stdout=StringIO())

        self.assertEqual(Student.objects.filter(group=StudyGroup.PILOT).count(), 3)
        self.assertEqual(Student.objects.filter(group=StudyGroup.CONTROL).count(), 4)

    def test_rejects_invalid_arguments(self):
        with self.assertRaises(CommandError):
            call_command("create_students", group="pilot", count=0, stdout=StringIO())
        with self.assertRaises(CommandError):
            call_command(
                "create_students", group="pilot", count=1, length=9, stdout=StringIO()
            )
        with self.assertRaises(CommandError):
            call_command("create_students", group="outro", count=1, stdout=StringIO())
