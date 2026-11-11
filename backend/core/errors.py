"""Domain exceptions shared by services and the API."""


class NotFound(LookupError):
    """A requested record does not exist (HTTP 404). Deliberately its own class: the API must NOT turn arbitrary
    KeyError/IndexError bugs (also LookupErrors) into a harmless-looking 404."""
