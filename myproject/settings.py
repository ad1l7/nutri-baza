from pathlib import Path
from decouple import config
import os

BASE_DIR = Path(__file__).resolve().parent.parent

# ── Безопасность ──────────────────────────────────────────────────────────────
SECRET_KEY = 'f^$ns03x0^0++xawzg2u71adjfy8&eo2zy%k#1s@y6y8!kpxd-'
DEBUG = config('DEBUG', default=False, cast=bool)

ALLOWED_HOSTS = ['olive-nutri-baza.kz', 'www.olive-nutri-baza.kz', '89.207.253.104', 'localhost', '127.0.0.1']

CSRF_TRUSTED_ORIGINS = [
    'https://olive-nutri-baza.kz',
    'https://www.olive-nutri-baza.kz',
]

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
IIKO_CLOUD_API_KEY    = "5ee9c3345f694fb7b08b24e488b4a141"
IIKO_ORG_ID           = "ce7007f2-fabd-4beb-886e-5e077f9aff66"
IIKO_EXTERNAL_MENU_ID = "78054"
IIKO_SERVER_URL       = "https://fudzavod.iiko.it/resto"
IIKO_SERVER_LOGIN     = "buh2"
IIKO_SERVER_PASSWORD  = "39babe20c3be152b70f15bb8383040d09852d1bb"

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
