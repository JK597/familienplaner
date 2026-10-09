const CACHE_NAME = "familienplaner-static-v3";

const STATIC_FILES = [
    "/static/style.css",
    "/static/manifest.webmanifest",
    "/static/icons/icon-192.png",
    "/static/icons/icon-512.png",
    "/static/icons/apple-touch-icon.png",
    "/static/icons/favicon-32.png"
];


/* =========================================================
   INSTALLATION
========================================================= */

self.addEventListener(
    "install",
    function(event) {

        event.waitUntil(

            caches
                .open(CACHE_NAME)
                .then(
                    function(cache) {

                        return cache.addAll(
                            STATIC_FILES
                        );

                    }
                )

        );

        self.skipWaiting();

    }
);


/* =========================================================
   AKTIVIERUNG
========================================================= */

self.addEventListener(
    "activate",
    function(event) {

        event.waitUntil(

            caches
                .keys()
                .then(
                    function(cacheNames) {

                        return Promise.all(

                            cacheNames.map(
                                function(cacheName) {

                                    if (
                                        cacheName !==
                                        CACHE_NAME
                                    ) {

                                        return caches.delete(
                                            cacheName
                                        );

                                    }

                                }
                            )

                        );

                    }
                )

        );

        self.clients.claim();

    }
);


/* =========================================================
   ANFRAGEN
========================================================= */

self.addEventListener(
    "fetch",
    function(event) {

        if (
            event.request.method !== "GET"
        ) {
            return;
        }


        const requestURL = new URL(
            event.request.url
        );


        /*
            Nur Dateien aus /static/ behandeln.
            Private Seiten wie Dashboard, Finanzen,
            Einkaufsliste und Vorschläge werden
            NICHT gecacht.
        */

        if (
            requestURL.origin ===
                self.location.origin
            &&
            requestURL.pathname.startsWith(
                "/static/"
            )
        ) {

            event.respondWith(

                fetch(
                    event.request
                )
                    .then(
                        function(networkResponse) {

                            if (
                                networkResponse
                                &&
                                networkResponse.ok
                            ) {

                                const responseClone =
                                    networkResponse.clone();


                                caches
                                    .open(CACHE_NAME)
                                    .then(
                                        function(cache) {

                                            cache.put(
                                                event.request,
                                                responseClone
                                            );

                                        }
                                    );

                            }


                            return networkResponse;

                        }
                    )
                    .catch(
                        function() {

                            return caches.match(
                                event.request
                            );

                        }
                    )

            );

            return;
        }


        /*
            Normale Seiten immer frisch
            vom Server holen.
        */

        event.respondWith(
            fetch(
                event.request
            )
        );

    }
);

/* =========================================================
   PUSH-BENACHRICHTIGUNGEN
========================================================= */

self.addEventListener(
    "push",
    function(event) {

        let daten = {
            title: "Familienplaner",
            body: "Du hast eine neue Benachrichtigung.",
            url: "/dashboard"
        };

        if (event.data) {

            try {

                daten = event.data.json();

            } catch (fehler) {

                daten.body =
                    event.data.text();

            }

        }

        const optionen = {

            body:
                daten.body
                || "Du hast eine neue Benachrichtigung.",

            icon:
                "/static/icons/icon-192.png",

            badge:
                "/static/icons/favicon-32.png",

            data: {
                url:
                    daten.url
                    || "/dashboard"
            },

            vibrate: [
                120,
                60,
                120
            ]
        };

        event.waitUntil(

            self.registration.showNotification(
                daten.title
                || "Familienplaner",
                optionen
            )

        );

    }
);


/* =========================================================
   KLICK AUF BENACHRICHTIGUNG
========================================================= */

self.addEventListener(
    "notificationclick",
    function(event) {

        event.notification.close();

        const ziel =
            event.notification.data
            &&
            event.notification.data.url
            ?
            event.notification.data.url
            :
            "/dashboard";

        event.waitUntil(

            clients
                .matchAll(
                    {
                        type: "window",
                        includeUncontrolled: true
                    }
                )
                .then(
                    function(clientListe) {

                        for (
                            const client of
                            clientListe
                        ) {

                            if (
                                "focus" in client
                            ) {

                                client.navigate(
                                    ziel
                                );

                                return client.focus();

                            }

                        }

                        if (
                            clients.openWindow
                        ) {

                            return clients.openWindow(
                                ziel
                            );

                        }

                    }
                )

        );

    }
);

