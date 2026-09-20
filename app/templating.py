from fastapi.templating import Jinja2Templates

templates = Jinja2Templates(directory="app/templates")


def fmt_date(value):
    if not value:
        return ""
    return value.strftime("%d %b %Y")


templates.env.filters["fmt_date"] = fmt_date
