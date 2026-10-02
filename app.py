from flask import Flask, request, redirect, session, render_template
import sqlite3
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = "mein_geheimer_schluessel_123"


# ----------------------------
# DATENBANK
# ----------------------------

def datenbank():
    db = sqlite3.connect("users.db")
    db.row_factory = sqlite3.Row
    return db


def datenbank_erstellen():
    db = datenbank()

    db.execute("""
        CREATE TABLE IF NOT EXISTS benutzer (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            benutzername TEXT UNIQUE NOT NULL,
            passwort TEXT NOT NULL,
            rolle TEXT NOT NULL
        )
    """)

    admin = db.execute(
        "SELECT * FROM benutzer WHERE rolle = ?",
        ("admin",)
    ).fetchone()

    if admin is None:
        db.execute(
            """
            INSERT INTO benutzer
            (benutzername, passwort, rolle)
            VALUES (?, ?, ?)
            """,
            (
                "joel",
                generate_password_hash("1234"),
                "admin"
            )
        )

    db.commit()
    db.close()


# ----------------------------
# LOGIN
# ----------------------------

@app.route("/", methods=["GET", "POST"])
def login():
    fehler = ""

    if request.method == "POST":
        benutzername = request.form["benutzername"].strip()
        passwort = request.form["passwort"]

        db = datenbank()

        benutzer = db.execute(
            "SELECT * FROM benutzer WHERE benutzername = ?",
            (benutzername,)
        ).fetchone()

        db.close()

        if benutzer and check_password_hash(
            benutzer["passwort"],
            passwort
        ):
            session["benutzer_id"] = benutzer["id"]
            session["benutzer"] = benutzer["benutzername"]
            session["rolle"] = benutzer["rolle"]

            return redirect("/dashboard")

        fehler = "Benutzername oder Passwort falsch."

    return render_template(
        "login.html",
        fehler=fehler
    )


# ----------------------------
# DASHBOARD
# ----------------------------

@app.route("/dashboard")
def dashboard():

    if "benutzer" not in session:
        return redirect("/")

    return render_template(
        "dashboard.html",
        benutzer=session["benutzer"],
        rolle=session["rolle"]
    )


# ----------------------------
# ADMIN
# ----------------------------

@app.route("/admin", methods=["GET", "POST"])
def admin():

    if session.get("rolle") != "admin":
        return redirect("/dashboard")

    meldung = ""

    if request.method == "POST":

        neuer_name = request.form["benutzername"].strip()
        neues_passwort = request.form["passwort"]

        if neuer_name == "":
            meldung = "Bitte einen Benutzernamen eingeben."

        elif neues_passwort == "":
            meldung = "Bitte ein Passwort eingeben."

        else:
            try:
                db = datenbank()

                db.execute(
                    """
                    INSERT INTO benutzer
                    (benutzername, passwort, rolle)
                    VALUES (?, ?, ?)
                    """,
                    (
                        neuer_name,
                        generate_password_hash(
                            neues_passwort
                        ),
                        "benutzer"
                    )
                )

                db.commit()
                db.close()

                meldung = "Benutzer wurde erstellt."

            except sqlite3.IntegrityError:
                meldung = "Dieser Benutzername existiert bereits."

    db = datenbank()

    benutzer_liste = db.execute(
        """
        SELECT id, benutzername, rolle
        FROM benutzer
        ORDER BY id
        """
    ).fetchall()

    db.close()

    return render_template(
        "admin.html",
        benutzer_liste=benutzer_liste,
        meldung=meldung
    )


# ----------------------------
# BENUTZERNAME ÄNDERN
# ----------------------------

@app.route(
    "/benutzername-aendern/<int:benutzer_id>",
    methods=["GET", "POST"]
)
def benutzername_aendern(benutzer_id):

    if session.get("rolle") != "admin":
        return redirect("/dashboard")

    db = datenbank()

    benutzer = db.execute(
        "SELECT * FROM benutzer WHERE id = ?",
        (benutzer_id,)
    ).fetchone()

    if benutzer is None:
        db.close()
        return redirect("/admin")

    meldung = ""

    if request.method == "POST":

        neuer_name = request.form["benutzername"].strip()

        if neuer_name == "":
            meldung = "Bitte einen Benutzernamen eingeben."

        else:
            try:
                db.execute(
                    """
                    UPDATE benutzer
                    SET benutzername = ?
                    WHERE id = ?
                    """,
                    (
                        neuer_name,
                        benutzer_id
                    )
                )

                db.commit()

                meldung = "Benutzername wurde geändert."

                if session.get("benutzer_id") == benutzer_id:
                    session["benutzer"] = neuer_name

                benutzer = db.execute(
                    "SELECT * FROM benutzer WHERE id = ?",
                    (benutzer_id,)
                ).fetchone()

            except sqlite3.IntegrityError:
                meldung = "Dieser Benutzername existiert bereits."

    db.close()

    return render_template(
        "benutzername.html",
        benutzer=benutzer,
        meldung=meldung
    )


# ----------------------------
# PASSWORT ÄNDERN
# ----------------------------

@app.route(
    "/passwort-aendern/<int:benutzer_id>",
    methods=["GET", "POST"]
)
def passwort_aendern(benutzer_id):

    if session.get("rolle") != "admin":
        return redirect("/dashboard")

    db = datenbank()

    benutzer = db.execute(
        "SELECT * FROM benutzer WHERE id = ?",
        (benutzer_id,)
    ).fetchone()

    if benutzer is None:
        db.close()
        return redirect("/admin")

    meldung = ""

    if request.method == "POST":

        neues_passwort = request.form["passwort"]

        if neues_passwort == "":
            meldung = "Bitte ein neues Passwort eingeben."

        else:
            db.execute(
                """
                UPDATE benutzer
                SET passwort = ?
                WHERE id = ?
                """,
                (
                    generate_password_hash(
                        neues_passwort
                    ),
                    benutzer_id
                )
            )

            db.commit()

            meldung = "Passwort wurde geändert."

    db.close()

    return render_template(
        "passwort.html",
        benutzer=benutzer,
        meldung=meldung
    )


# ----------------------------
# BENUTZER LÖSCHEN
# ----------------------------

@app.route(
    "/benutzer-loeschen/<int:benutzer_id>",
    methods=["POST"]
)
def benutzer_loeschen(benutzer_id):

    if session.get("rolle") != "admin":
        return redirect("/dashboard")

    db = datenbank()

    benutzer = db.execute(
        "SELECT * FROM benutzer WHERE id = ?",
        (benutzer_id,)
    ).fetchone()

    if benutzer and benutzer["rolle"] != "admin":

        db.execute(
            "DELETE FROM benutzer WHERE id = ?",
            (benutzer_id,)
        )

        db.commit()

    db.close()

    return redirect("/admin")


# ----------------------------
# LOGOUT
# ----------------------------

@app.route("/logout")
def logout():

    session.clear()

    return redirect("/")


# ----------------------------
# SERVER STARTEN
# ----------------------------

if __name__ == "__main__":

    datenbank_erstellen()

    app.run(debug=True)