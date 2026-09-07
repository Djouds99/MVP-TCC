"""
Configuracao do MVP de recomendacao KST.

Toda a configuracao sensivel ao ambiente vem de variaveis de ambiente, para que o
mesmo codigo rode em desenvolvimento e na hospedagem sem edicao de arquivo.
Ver `.env.example` para a lista completa.
"""

import os
from pathlib import Path

import dj_database_url

BASE_DIR = Path(__file__).resolve().parent.parent


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_list(name: str) -> list[str]:
    raw = os.environ.get(name, "")
    return [item.strip() for item in raw.split(",") if item.strip()]


DEBUG = _env_bool("DJANGO_DEBUG", True)

# Em desenvolvimento uma chave fixa e aceitavel; em producao a ausencia da
# variavel e erro de configuracao, nao algo para degradar silenciosamente.
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "")
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = "dev-only-nao-usar-em-producao"
    else:
        raise RuntimeError(
            "DJANGO_SECRET_KEY e obrigatoria quando DJANGO_DEBUG=0."
        )

ALLOWED_HOSTS = _env_list("DJANGO_ALLOWED_HOSTS") or (
    ["127.0.0.1", "localhost"] if DEBUG else []
)
CSRF_TRUSTED_ORIGINS = _env_list("DJANGO_CSRF_TRUSTED_ORIGINS")

# O Render publica o dominio do servico em RENDER_EXTERNAL_HOSTNAME. Usar essa
# variavel evita ter que reeditar a configuracao quando o dominio muda; em outra
# hospedagem ela simplesmente nao existe e nada acontece.
_render_hostname = os.environ.get("RENDER_EXTERNAL_HOSTNAME")
if _render_hostname:
    if _render_hostname not in ALLOWED_HOSTS:
        ALLOWED_HOSTS.append(_render_hostname)
    _render_origin = f"https://{_render_hostname}"
    if _render_origin not in CSRF_TRUSTED_ORIGINS:
        CSRF_TRUSTED_ORIGINS.append(_render_origin)

INSTALLED_APPS = [
    # Desliga o servico de estaticos do runserver para que o WhiteNoise seja
    # exercitado tambem em desenvolvimento — o comportamento de producao deixa
    # de ser uma surpresa no dia do deploy.
    "whitenoise.runserver_nostatic",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "domain",
    "students",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# SQLite por padrao (CLAUDE.md secao 6). DATABASE_URL, quando presente, tem
# prioridade — e o caminho de migracao para Postgres sem mexer em codigo.
_sqlite_path = os.environ.get("DJANGO_SQLITE_PATH") or (BASE_DIR / "db.sqlite3")
DATABASES = {
    "default": dj_database_url.config(
        default=f"sqlite:///{_sqlite_path}",
        conn_max_age=600,
        conn_health_checks=True,
    )
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "pt-br"
TIME_ZONE = "America/Sao_Paulo"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"
    },
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Endurecimento aplicado apenas fora de DEBUG: em desenvolvimento o redirect
# para HTTPS impediria o acesso por http://127.0.0.1.
if not DEBUG:
    # Desligavel por variavel de ambiente por dois motivos: permite exercitar a
    # configuracao de producao localmente sobre http, e algumas hospedagens ja
    # redirecionam para HTTPS na borda, caso em que redirecionar de novo aqui so
    # acrescenta um salto.
    SECURE_SSL_REDIRECT = _env_bool("DJANGO_SECURE_SSL_REDIRECT", True)
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 3600
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "INFO"},
}
