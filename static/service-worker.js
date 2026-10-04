const CACHE_NAME = "familienplaner-static-v1";

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

self.addEventListener("install", function(event) {

    event.waitUntil(

        caches.open(CACHE_NAME)
            .then(function(cache) {

                return cache.addAll(
                    STATIC_FILES
                );

            })

    );

    self.skipWaiting();

});


/* =========================================================
   AKTIVIERUNG
========================================================= */

self.addEventListener("activate", function(event) {

    event.waitUntil(

        caches.keys()
            .then(function(cacheNames) {

                return Promise.all(

                    cacheNames.map(
                        function(cacheName) {

                            if (
                                cacheName !== CACHE_NAME
                            ) {

                                return caches.delete(
                                    cacheName
                                );

                            }

                        }
                    )

                );

            })

    );

    self.clients.claim();

});


/* =========================================================
   ANFRAGEN
========================================================= */

self.addEventListener("fetch", function(event) {

    if (
        event.request.method !== "GET"
    ) {
        return;
    }


    const requestURL =
        new URL(
            event.request.url
        );


    /*
        Nur statische Dateien cachen.
        Seiten wie Finanzen, Einkaufsliste,
        Dashboard usw. kommen immer frisch
        vom Server.
    */

    if (
        requestURL.origin === self.location.origin
        &&
        requestURL.pathname.startsWith("/static/")
    ) {

        event.respondWith(

            caches.match(
                event.request
            )

                .then(function(cachedResponse) {

                    if (cachedResponse) {

                        return cachedResponse;

                    }


                    return fetch(
                        event.request
                    )

                        .then(
                            function(networkResponse) {

                                const responseClone =
                                    networkResponse.clone();


                                caches.open(
                                    CACHE_NAME
                                )

                                    .then(
                                        function(cache) {

                                            cache.put(
                                                event.request,
                                                responseClone
                                            );

                                        }
                                    );


                                return networkResponse;

                            }
                        );

                })

        );

        return;
    }


    /*
        Alle normalen Seiten immer
        frisch vom Server laden.
    */

    event.respondWith(
        fetch(
            event.request
        )
    );

});