import requests

def fuxnoten_login_and_account():
    # 1) Session erstellen (verwaltet automatisch Cookies)
    session = requests.Session()

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
        secure=True,  # Falls es sich um einen Secure-Cookie handelt
        # httponly=True  # Kannst du nicht clientseitig setzen, das ist ein Server-Attribut.
    )
    
    # 2) URL für den Login-POST
    login_url = "https://100308.fuxnoten.online/webinfo"
    
    # 3) Form-Daten (x-www-form-urlencoded)
    #    Werte ggf. anpassen, wenn _nonce oder _f_secure sich ändern!
    payload = {
        "user": "gia-gis-001-00610",
        "password": "Gia-gis-001-00610!",
        "fuxnoten_post_controller": "\\Objects\\Webinfo_Object",
        "_f_action": "login",
        "_referrer": "https://100308.fuxnoten.online/webinfo/checkin/checkout/",
        "_nonce": "4f5e7a657d0a88f5d0969c26c2b07baf",
        "_f_secure": ""  # Hier ggf. Token einfügen, falls notwendig
    }
    
    # 4) Header vorbereiten
    #    Falls dein Server bestimmte Header erwartet, füge sie hier ein.
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) "
            "Version/16.0 Safari/605.1.15"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "Referer": "https://100308.fuxnoten.online/webinfo/checkin/checkout/",
        "Content-Type": "application/x-www-form-urlencoded"
    }
    
    # 5) Login-Request (POST)
    #    allow_redirects=True sorgt dafür, dass requests automatisch 302/303-Redirects folgt.
    login_response = session.post(login_url, data=payload, headers=headers, allow_redirects=True)
    print("Login response status:", login_response.status_code)
    print("Login response URL:", login_response.url)
    print("Login response Data:", login_response.text)
    # Optional: print(login_response.text)  # HTML-Quelltext des Redirect-Ziels
    
    # 6) Authentifizierte Seite abrufen (z. B. /webinfo/account/)
    #account_url = "https://100308.fuxnoten.online/webinfo/account/"
    #account_response = session.get(account_url, headers=headers)
    #print("Account response status:", account_response.status_code)
    #print("Account response URL:", account_response.url)
    #print("Account page content:")
    #print(account_response.text)

if __name__ == "__main__":
    fuxnoten_login_and_account()
