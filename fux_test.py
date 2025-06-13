import requests

def main():
    # 1) Eine neue Session erstellen
    session = requests.Session()

    # 2) Gewünschte Cookies manuell in die Session eintragen
    #    Wichtig: Du kannst Domain und Path angeben, damit der Cookie korrekt zugeordnet wird.
    session.cookies.set(
        name="euCookie",
        value="set",  # aus deinem Screenshot
        domain="100308.fuxnoten.online",  # Domain anpassen!
        path="/"
        # secure=True  # Falls nötig, kannst du Secure auf True setzen.
    )

    session.cookies.set(
        name="fux23-25290",
        value="3242082eb3b9e04962dc3e0ba19e2b19",  # aus deinem Screenshot
        domain="100308.fuxnoten.online",
        path="/",
        # secure=True,  # Falls es sich um einen Secure-Cookie handelt
        # httponly=True  # Kannst du nicht clientseitig setzen, das ist ein Server-Attribut.
    )

    # 3) Beispiel: Einen GET-Request machen, der die Cookies nutzt
    url = "https://100308.fuxnoten.online/webinfo/"
    response = session.post(url)

    print("Status Code:", response.status_code)
    print("Response URL:", response.url)
    print("Response Body:\n", response.text)

if __name__ == "__main__":
    main()
