from sqlalchemy.engine import make_url

from pawlocal.config import Settings


def test_compose_database_fields_preserve_url_special_password_characters():
    password = "value@with:/?#%[]reserved"
    settings = Settings(
        _env_file=None,
        database_host="postgres",
        database_port=5432,
        database_name="pawlocal",
        database_user="pawlocal",
        database_password=password,
    )

    url = settings.sqlalchemy_url
    assert url.password == password
    assert url.host == "postgres"
    assert url.port == 5432
    assert url.database == "pawlocal"
    assert make_url(url.render_as_string(hide_password=False)).password == password
