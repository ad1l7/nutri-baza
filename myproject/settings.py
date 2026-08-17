from pathlib import Path
from decouple import config
import os

BASE_DIR = Path(__file__).resolve().parent.parent

# ── Безопасность ──────────────────────────────────────────────────────────────
# Все секреты берутся из .env (файл в .gitignore, в репозиторий не попадает).
SECRET_KEY = config('SECRET_KEY')
DEBUG = config('DEBUG', default=False, cast=bool)

ALLOWED_HOSTS = ['olive-nutri-baza.kz', 'www.olive-nutri-baza.kz', '89.207.253.104', 'localhost', '127.0.0.1']

CSRF_TRUSTED_ORIGINS = [
    'https://olive-nutri-baza.kz',
    'https://www.olive-nutri-baza.kz',
]

# Токен для /api/ — по нему ERP забирает каталог блюд, чтобы печатать этикетки
# у себя. Значение в .env; пустое = API закрыт полностью.
LABEL_API_TOKEN = config('LABEL_API_TOKEN', default='')

# ── База данных ───────────────────────────────────────────────────────────────
# Если USE_SQLITE=True в .env — локальная разработка на SQLite
# Если USE_SQLITE не задан — PostgreSQL (продакшн)
if config('USE_SQLITE', default=False, cast=bool):
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': config('DB_NAME', default='myproject_db'),
            'USER': config('DB_USER', default='postgres'),
            'PASSWORD': config('DB_PASSWORD', default='postgres'),
            'HOST': 'localhost',
            'PORT': '5432',
        }
    }

# ── Медиа ─────────────────────────────────────────────────────────────────────
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# ── iiko ─────────────────────────────────────────────────────────────────────
# Значения — в .env. Новый метод авторизации Cloud API (iikoTransport) через
# appId+clientSecret; старый /api/1/access_token отключается iiko ~29.08.2026.
IIKO_CLOUD_API_KEY    = config("IIKO_CLOUD_API_KEY")
IIKO_ORG_ID           = config("IIKO_ORG_ID")
IIKO_EXTERNAL_MENU_ID = config("IIKO_EXTERNAL_MENU_ID")
IIKO_APP_ID           = config("IIKO_APP_ID")
IIKO_CLIENT_SECRET    = config("IIKO_CLIENT_SECRET")
IIKO_SERVER_URL       = config("IIKO_SERVER_URL")
IIKO_SERVER_LOGIN     = config("IIKO_SERVER_LOGIN")
IIKO_SERVER_PASSWORD  = config("IIKO_SERVER_PASSWORD")

# ── Claude (Anthropic API) ────────────────────────────────────────────────────
ANTHROPIC_API_KEY = config("ANTHROPIC_API_KEY", default="")

# ── Логи ──────────────────────────────────────────────────────────────────────
# Пишем в stdout: gunicorn его перехватывает, читать через
#   journalctl -u gunicorn -f | grep claude
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "simple": {"format": "[{asctime}] {levelname} {name}: {message}", "style": "{"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "simple"},
    },
    "loggers": {
        "myapp": {"handlers": ["console"], "level": "INFO", "propagate": False},
    },
}

# ── Приложения ────────────────────────────────────────────────────────────────
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'myapp',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'myapp.middleware.LoginRequiredMiddleware',
    'myapp.middleware.ReaderReadOnlyMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

# ── Авторизация ───────────────────────────────────────────────────────────────
LOGIN_URL = '/login/'
LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/login/'

ROOT_URLCONF = 'myproject.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'myapp.context_processors.user_role',
            ],
        },
    },
]

WSGI_APPLICATION = 'myproject.wsgi.application'

# ── Валидация паролей ─────────────────────────────────────────────────────────
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# ── Интернационализация ───────────────────────────────────────────────────────
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_L10N = True
USE_TZ = True

# ── Статика ───────────────────────────────────────────────────────────────────
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'

# Тип авто-PK (совпадает с тем, что уже создано в БД)
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
