"""
Formularios do fluxo do aluno.

Tudo server-rendered, sem JavaScript: em escola publica o dispositivo e a rede
sao imprevisiveis, e o caminho critico do piloto nao pode depender de script
carregando. Validacao acontece no servidor, que e onde ela conta.
"""

from django import forms

from domain.models import Topic
from students.codes import MAX_CODE_LENGTH, normalize_code
from students.models import Student


class StudentCodeForm(forms.Form):
    """Identificacao do aluno pelo codigo curto entregue pelo professor."""

    code = forms.CharField(
        label="Seu código",
        # Folga sobre o tamanho real para acomodar espaco ou hifen digitado;
        # `normalize_code` limpa isso antes da busca.
        max_length=MAX_CODE_LENGTH + 6,
        strip=True,
        widget=forms.TextInput(
            attrs={
                "placeholder": "Ex.: 7KMQ2",
                "autocapitalize": "characters",
                "autocomplete": "off",
                "autocorrect": "off",
                "spellcheck": "false",
                "inputmode": "text",
                "autofocus": "autofocus",
            }
        ),
    )

    def clean_code(self) -> str:
        code = normalize_code(self.cleaned_data["code"])
        if not code:
            raise forms.ValidationError("Digite o código que o professor entregou.")

        try:
            self.student = Student.objects.get(code=code)
        except Student.DoesNotExist:
            raise forms.ValidationError(
                "Não encontramos esse código. Confira as letras e os números e "
                "tente de novo."
            ) from None
        return code


class GoalForm(forms.Form):
    """Objetivo declarado pelo aluno, escolhido no nivel de topico."""

    topic = forms.ModelChoiceField(
        queryset=Topic.objects.order_by("position", "code"),
        label="O que você quer aprender?",
        empty_label=None,
        widget=forms.RadioSelect,
    )


class AnswerForm(forms.Form):
    """
    Uma resposta do aluno.

    `question` viaja no formulario para que a view possa recusar um envio velho
    — aluno que volta pelo botao do navegador e responde de novo uma questao ja
    respondida.
    """

    question = forms.IntegerField(widget=forms.HiddenInput)
    alternative = forms.IntegerField(min_value=0, required=False)
