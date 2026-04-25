from functools import wraps

from flask import abort, flash, redirect, url_for
from flask_login import current_user, login_required


def vip_required(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if current_user.is_admin or current_user.vip_active:
            return view(*args, **kwargs)
        flash("Unlock VIP access to view real-time Pokémon TCG deals.", "warning")
        return redirect(url_for("main.vip_pending"))

    return wrapped


def admin_required(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if current_user.is_admin:
            return view(*args, **kwargs)
        abort(403)

    return wrapped
