import os
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit
from dotenv import load_dotenv

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

load_dotenv(BASE_DIR / ".env")


ROLE = os.environ.get("ROLE", "master")
HA_ENABLED = os.environ.get("HA_ENABLED", "False").lower() == "true"

SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-change-me")
DEBUG = os.environ.get("DEBUG", "True").lower() == "true"
ALLOWED_HOSTS = [h.strip() for h in os.environ.get("ALLOWED_HOSTS", "*").split(",") if h.strip()]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
]
if ROLE in {"master", "controller"}:
    INSTALLED_APPS += ["vault"]
else:
    INSTALLED_APPS += ["node"]
if ROLE == "controller":
    INSTALLED_APPS += ["node"]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "db.sqlite3"}}
if ROLE in {"master", "controller"}:
    db_url = os.environ.get("DATABASE_URL")
    if db_url and db_url.startswith("postgres"):
        parsed_db_url = urlsplit(db_url)
        query = parse_qs(parsed_db_url.query)
        DATABASES["default"] = {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": unquote(parsed_db_url.path.lstrip("/")),
            "USER": unquote(parsed_db_url.username or ""),
            "PASSWORD": unquote(parsed_db_url.password or ""),
            "HOST": parsed_db_url.hostname or "",
            "PORT": str(parsed_db_url.port or ""),
            "OPTIONS": {
                "sslmode": query.get(
                    "sslmode",
                    [os.environ.get("POSTGRES_SSLMODE", "prefer")],
                )[0]
            },
        }
if HA_ENABLED and DATABASES["default"]["ENGINE"] != "django.db.backends.postgresql":
    raise RuntimeError("HA_ENABLED requires DATABASE_URL to use PostgreSQL")

AUTH_PASSWORD_VALIDATORS = []
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True
STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {"context_processors": [
            "django.template.context_processors.request",
            "django.contrib.auth.context_processors.auth",
            "django.contrib.messages.context_processors.messages",
        ]},
    }
]

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["rest_framework.authentication.SessionAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
}

CLUSTER_SECRET = os.environ.get("CLUSTER_SECRET", "dev-cluster-secret")
REPLICATION_FACTOR = int(os.environ.get("REPLICATION_FACTOR", "2"))
HEARTBEAT_INTERVAL_SECONDS = int(os.environ.get("HEARTBEAT_INTERVAL_SECONDS", "5"))
NODE_DEAD_AFTER_SECONDS = int(os.environ.get("NODE_DEAD_AFTER_SECONDS", "15"))
MONITOR_INTERVAL_SECONDS = int(os.environ.get("MONITOR_INTERVAL_SECONDS", "5"))
MAX_UPLOAD_BYTES = int(os.environ.get("MAX_UPLOAD_BYTES", "104857600"))
DATA_UPLOAD_MAX_MEMORY_SIZE = MAX_UPLOAD_BYTES

NODE_NAME = os.environ.get("NODE_NAME", "")
NODE_ADDRESS = os.environ.get("NODE_ADDRESS", "")
NODE_DATA_DIR = os.environ.get("NODE_DATA_DIR", "./data")
NODE_CAPACITY_BYTES = int(os.environ.get("NODE_CAPACITY_BYTES", "0"))
MASTER_URL = os.environ.get("MASTER_URL", "")
CONTROL_PLANE_DNS = os.environ.get("CONTROL_PLANE_DNS", "lanvault.local")
PATRONI_SCOPE = os.environ.get("PATRONI_SCOPE", "lanvault")
