/* Familienplaner Service Worker
   Fokus: Push-Benachrichtigungen.
   Keine Vorab-Caches, damit die Installation nicht an einer fehlenden
   statischen Datei scheitern kann.
*/

self.addEventListener("install", function(event) {
    self.skipWaiting();
});

self.addEventListener("activate", function(event) {
    event.waitUntil(self.clients.claim());
});

self.addEventListener("fetch", function(event) {
    // Seiten und Dateien normal vom Netzwerk laden.
    // Kein event.respondWith nötig.
});

self.addEventListener("push", function(event) {
    let daten = {
        title: "Familienplaner",
        body: "Du hast eine neue Benachrichtigung.",
        url: "/dashboard"
    };

    if (event.data) {
        try {
            daten = event.data.json();
        } catch (fehler) {
            daten.body = event.data.text();
        }
    }

    const optionen = {
        body: daten.body || "Du hast eine neue Benachrichtigung.",
        icon: "/static/icons/icon-192.png",
        badge: "/static/icons/favicon-32.png",
        data: {
            url: daten.url || "/dashboard"
        }
    };

    event.waitUntil(
        self.registration.showNotification(
            daten.title || "Familienplaner",
            optionen
        )
    );
});

self.addEventListener("notificationclick", function(event) {
    event.notification.close();

    const ziel =
        event.notification.data &&
        event.notification.data.url
            ? event.notification.data.url
            : "/dashboard";

    event.waitUntil(
        self.clients.matchAll({
            type: "window",
            includeUncontrolled: true
        }).then(function(clientListe) {
            for (const client of clientListe) {
                if ("focus" in client) {
                    if ("navigate" in client) {
                        client.navigate(ziel);
                    }
                    return client.focus();
                }
            }

            if (self.clients.openWindow) {
                return self.clients.openWindow(ziel);
            }
        })
    );
});
