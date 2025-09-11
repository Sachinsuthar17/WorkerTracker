import os


class Config:
    """Configuration for the Flask app and database.

    - ``SQLALCHEMY_DATABASE_URI``: defaults to a local PostgreSQL database named
      ``garment_erp`` but can be overridden via the ``DATABASE_URL`` environment
      variable.  This parameter tells SQLAlchemy which database to connect to.
    - ``SQLALCHEMY_TRACK_MODIFICATIONS``: disables the event system which
      otherwise adds overhead.  The event system is rarely needed and can be
      safely turned off for most applications.
    - ``SECRET_KEY``: used by Flask for session signing.  In production you
      should set this to a strong random value via the environment.
    - ``JSON_SORT_KEYS``: prevents Flask from alphabetically sorting keys in
      JSON responses, preserving insertion order instead.
    """

    SQLALCHEMY_DATABASE_URI = os.getenv(
        "DATABASE_URL",
        "postgresql+psycopg2://postgres:postgres@localhost:5432/garment_erp",
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SECRET_KEY = os.getenv("SECRET_KEY", "change-me")
    JSON_SORT_KEYS = False