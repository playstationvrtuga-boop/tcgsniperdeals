SEO_PUBLIC_PATHS = [
    "/",
    "/download-app",
    "/pokemon-deals",
    "/pokemon-card-deals",
    "/charizard-deals",
    "/etb-deals",
    "/booster-box-deals",
    "/graded-pokemon-cards",
    "/vinted-pokemon-deals",
    "/ebay-pokemon-deals",
    "/cheap-pokemon-cards",
]


SEO_PAGE_ALIASES = {
    "pokemon-etb-deals": "etb-deals",
    "pokemon-booster-deals": "booster-box-deals",
    "pokemon-vinted-deals": "vinted-pokemon-deals",
    "pokemon-ebay-deals": "ebay-pokemon-deals",
}


SEO_HOME_CONTENT = {
    "eyebrow": "Pokemon TCG deal tracking",
    "title": "Real-time Pokemon TCG deals from eBay and Vinted",
    "text": (
        "TCG Sniper Deals tracks fresh Pokemon TCG listings from marketplaces like eBay and Vinted, then turns the stream into a faster way to spot cards, sealed products and underpriced opportunities. "
        "The public website shows how the system works, while VIP access unlocks the live app experience with real-time alerts, direct listing links and a cleaner view of the strongest opportunities. "
        "Collectors and resellers use this kind of monitoring because strong listings can disappear quickly, especially when a seller prices a Charizard card, an Elite Trainer Box, a booster box, a PSA slab or a collection bundle below normal market value."
    ),
    "sections": [
        {
            "title": "Why real-time Pokemon deal detection matters",
            "text": (
                "Manual searching is slow. A good Pokemon card deal may be live for only a few minutes before another buyer finds it. "
                "TCG Sniper Deals is built around speed, recency and clear marketplace signals, so users can see newly detected listings without refreshing search pages all day. "
                "The feed is designed for practical decisions: title, image, source, price, detection time and direct action."
            ),
        },
        {
            "title": "Marketplace coverage",
            "text": (
                "The system monitors Pokemon listings from eBay and Vinted, including singles, graded cards, slabs, ETBs, booster boxes, sealed collections, bundles and other TCG products. "
                "Examples include Charizard cards, Pikachu cards, vintage WOTC singles, modern illustration rares, PSA graded cards, Beckett slabs, sealed booster products and Elite Trainer Boxes. "
                "Availability always depends on the marketplace and sellers can remove, reserve or sell listings at any time."
            ),
        },
        {
            "title": "VIP app and free Telegram funnel",
            "text": (
                "VIP access is the paid product inside the app and website. VIP users get the full live stream, real-time alerts and direct access to listings. "
                "The free Telegram channel is only a discovery funnel with limited public samples and promotional updates. "
                "That separation keeps the paid app focused on speed while still giving new users a way to understand the value before upgrading."
            ),
        },
    ],
    "links": [
        ("Pokemon deals", "main.seo_page_pokemon_deals"),
        ("Pokemon card deals", "main.seo_page_pokemon_card_deals"),
        ("Charizard deals", "main.seo_page_charizard_deals"),
        ("ETB deals", "main.seo_page_etb_deals"),
        ("Booster box deals", "main.seo_page_booster_box_deals"),
        ("Graded Pokemon cards", "main.seo_page_graded_pokemon_cards"),
        ("Vinted Pokemon deals", "main.seo_page_vinted_pokemon_deals"),
        ("eBay Pokemon deals", "main.seo_page_ebay_pokemon_deals"),
    ],
}


SEO_PAGES = {
    "pokemon-deals": {
        "title": "Real-Time Pokemon TCG Deals | TCG Sniper Deals",
        "meta_description": "Find real-time Pokemon TCG deals, Charizard cards, ETBs, booster boxes, slabs and sealed products from eBay and Vinted.",
        "h1": "Real-Time Pokemon TCG Deals",
        "intro": (
            "TCG Sniper Deals helps collectors and resellers discover Pokemon TCG opportunities faster. "
            "The app monitors listings from marketplaces like eBay and Vinted, then surfaces new Pokemon cards, booster boxes, Elite Trainer Boxes, sealed products, graded slabs and collection bundles in a live stream. "
            "The goal is not to replace research. It is to reduce the time between a listing appearing and a serious buyer seeing it."
        ),
        "sections": [
            {
                "title": "Why speed matters in Pokemon deals",
                "text": (
                    "The strongest Pokemon TCG deals usually do not stay available for long. Charizard cards, vintage singles, booster boxes, ETBs and sealed Pokemon products can sell within minutes when a seller lists them below normal market value. "
                    "A slow manual search means checking the same marketplace pages again and again, often after someone else has already bought the listing. "
                    "TCG Sniper Deals focuses on real-time detection, clear source labels, images, prices and direct listing access so VIP users can react while the opportunity is still live."
                ),
            },
            {
                "title": "What the system tracks",
                "text": (
                    "The live feed is built around practical Pokemon TCG searches: single cards, graded PSA slabs, Beckett and CGC cards, booster packs, booster boxes, Elite Trainer Boxes, tins, collection boxes, lots and sealed products. "
                    "It can surface listings from eBay and Vinted when the bot detects titles, images and marketplace signals that look relevant to Pokemon collectors or resellers. "
                    "Deals are never guaranteed, and marketplace availability can change quickly, but faster discovery gives users a better chance to inspect and act."
                ),
            },
            {
                "title": "VIP alerts and free previews",
                "text": (
                    "The paid VIP app is where the full real-time stream lives. VIP users get direct links, live cards, saved opportunities and stronger pricing signals when available. "
                    "The free Telegram channel is intentionally limited and works as a public preview, not a replacement for the app. "
                    "If you collect, resell or flip Pokemon cards, this difference matters because the value is often in seeing the listing before the wider market catches up."
                ),
            },
        ],
        "related": ["pokemon-card-deals", "charizard-deals", "etb-deals", "booster-box-deals", "vinted-pokemon-deals", "ebay-pokemon-deals"],
    },
    "pokemon-card-deals": {
        "title": "Pokemon Card Deals | Real-Time Card Alerts",
        "meta_description": "Track Pokemon card deals, cheap singles, slabs, rare cards and underpriced listings from eBay and Vinted.",
        "h1": "Pokemon Card Deals",
        "intro": (
            "Pokemon card deals can appear in many forms: raw singles, reverse holos, illustration rares, vintage cards, graded slabs, binder lots and collection bundles. "
            "TCG Sniper Deals helps users follow new marketplace listings without relying only on manual searches. "
            "The system is designed for collectors and resellers who want faster visibility when a card is listed at an interesting price."
        ),
        "sections": [
            {
                "title": "Raw cards, slabs and collection lots",
                "text": (
                    "A strong Pokemon card opportunity is not always obvious from a perfect title. Sellers may write incomplete names, use another language, include only a card number or upload a mixed bundle with several cards in one photo. "
                    "The tracking flow is built to catch a broader range of Pokemon listings, including PSA, Beckett and CGC graded cards, raw singles, vintage cards and mixed lots. "
                    "That wider coverage helps reduce the chance of missing useful listings just because the seller did not write a clean product name."
                ),
            },
            {
                "title": "Useful for collectors and flippers",
                "text": (
                    "Collectors use fast alerts to find cards for a personal collection before prices move. Resellers use them to inspect possible spreads between listing price and market value. "
                    "TCG Sniper Deals does not guarantee profit, but it gives a cleaner starting point by bringing fresh eBay and Vinted Pokemon card listings into one live dashboard. "
                    "Users still need to check condition, language, seller feedback, shipping cost and authenticity before buying."
                ),
            },
            {
                "title": "From public discovery to VIP access",
                "text": (
                    "The public website explains the product and shows how the live stream works. The full paid VIP app provides the real-time feed, direct listing links and app alerts. "
                    "Free Telegram samples can show examples, but the app is the main product for people who want the fastest view of new Pokemon card deals."
                ),
            },
        ],
        "related": ["pokemon-deals", "charizard-deals", "graded-pokemon-cards", "cheap-pokemon-cards", "vinted-pokemon-deals", "ebay-pokemon-deals"],
    },
    "charizard-deals": {
        "title": "Charizard Card Deals | Real-Time Pokemon Alerts",
        "meta_description": "Track Charizard Pokemon card deals, underpriced listings, graded slabs and real-time marketplace alerts.",
        "h1": "Charizard Card Deals",
        "intro": (
            "Charizard is one of the most searched and collected Pokemon cards worldwide. "
            "Because demand is high, good Charizard deals often disappear quickly across eBay, Vinted and other secondary marketplaces. "
            "TCG Sniper Deals helps users watch for fresh Charizard listings so they can inspect price, condition, image and seller information faster."
        ),
        "sections": [
            {
                "title": "Find Charizard listings faster",
                "text": (
                    "Charizard cards appear in many formats: vintage base set cards, modern Charizard ex cards, VSTAR cards, full arts, secret rares, graded PSA slabs and mixed collection bundles. "
                    "A seller may write Charizard perfectly, use a card number, include only part of a set name or describe the item in another language. "
                    "A real-time tracking flow gives users a better chance to catch those listings before they are gone."
                ),
            },
            {
                "title": "What to check before buying",
                "text": (
                    "Fast alerts are useful, but every Charizard listing still needs careful inspection. Buyers should check photos, card condition, language, grade, certification number, seller feedback and shipping costs. "
                    "The app is designed to bring the opportunity to the user quickly, not to remove the need for judgement. "
                    "That balance is important for collectors and resellers who want speed without careless purchases."
                ),
            },
            {
                "title": "VIP first look advantage",
                "text": (
                    "The free channel may show limited examples, but full access is inside the VIP app. "
                    "VIP users can open the direct listing, save opportunities and follow the live feed as new Charizard-related listings appear. "
                    "For cards with high demand, that first-look timing can be the difference between inspecting a live deal and seeing a sold page later."
                ),
            },
        ],
        "related": ["pokemon-deals", "pokemon-card-deals", "graded-pokemon-cards", "ebay-pokemon-deals", "vinted-pokemon-deals"],
    },
    "etb-deals": {
        "title": "Pokemon ETB Deals | Elite Trainer Box Alerts",
        "meta_description": "Find Pokemon Elite Trainer Box deals, ETB discounts and sealed Pokemon TCG product alerts.",
        "h1": "Pokemon ETB Deals",
        "intro": (
            "Elite Trainer Boxes are one of the most popular sealed Pokemon TCG products for collectors, players and resellers. "
            "They are recognizable, easy to compare and often move quickly when priced below normal market value. "
            "TCG Sniper Deals helps track new ETB listings from marketplaces like eBay and Vinted."
        ),
        "sections": [
            {
                "title": "Track sealed Pokemon products",
                "text": (
                    "ETB listings can include current sets, older sealed products, special collections and bundles with packs or accessories. "
                    "Sellers may call them Elite Trainer Boxes, ETBs, trainer boxes, coffrets, boxes or sealed Pokemon products. "
                    "The live feed is designed to surface those listings quickly so users can compare price, photos and seller details while the item is still available."
                ),
            },
            {
                "title": "Why ETBs matter",
                "text": (
                    "Pokemon ETBs are popular because they are sealed, easy to store and familiar to many buyers. "
                    "When a sealed box is listed too cheaply, collectors may want it for a personal collection and resellers may see a possible margin. "
                    "The system helps users discover those opportunities faster, but buyers should still check language, set, box condition, shipping and whether the seal looks authentic."
                ),
            },
            {
                "title": "Real-time access",
                "text": (
                    "The VIP app provides the full stream and direct listing access. "
                    "Free Telegram updates are limited and cannot replace a real-time dashboard when sealed products are moving fast. "
                    "For ETBs, speed matters because a fairly priced sealed box can be bought quickly by collectors watching the same marketplaces."
                ),
            },
        ],
        "related": ["pokemon-deals", "booster-box-deals", "vinted-pokemon-deals", "ebay-pokemon-deals", "cheap-pokemon-cards"],
    },
    "booster-box-deals": {
        "title": "Pokemon Booster Box Deals | Real-Time TCG Alerts",
        "meta_description": "Track Pokemon booster box deals, booster packs and sealed pack listings with real-time TCG alerts.",
        "h1": "Pokemon Booster Box Deals",
        "intro": (
            "Booster boxes, booster packs and sealed Pokemon TCG products are among the most searched items in the hobby. "
            "Prices can move quickly when a seller lists a sealed product below market value, especially for popular or older sets. "
            "TCG Sniper Deals helps users follow fresh booster-related listings in a fast, mobile-friendly feed."
        ),
        "sections": [
            {
                "title": "Find booster pack opportunities",
                "text": (
                    "The system can surface listings for booster boxes, loose booster packs, sealed displays, blister packs, collection boxes and mixed sealed bundles. "
                    "Marketplace titles are often inconsistent, so useful listings may not always contain the exact product name. "
                    "A broader live feed helps users catch relevant sealed Pokemon listings and review them before the opportunity disappears."
                ),
            },
            {
                "title": "React before deals disappear",
                "text": (
                    "Good booster deals can sell fast because sealed Pokemon products attract collectors, players and investors. "
                    "Fast detection helps users check whether the listing is real, whether the price is interesting and whether shipping or condition changes the value. "
                    "TCG Sniper Deals focuses on bringing fresh opportunities into one place rather than forcing users to search multiple marketplace pages manually."
                ),
            },
            {
                "title": "VIP live stream",
                "text": (
                    "VIP users get the full live feed and direct links inside the app. "
                    "Public pages explain the service and help Google understand the topic, while the paid app remains the main product for real-time booster box and sealed product alerts. "
                    "Availability depends on sellers and marketplaces, so speed and verification both matter."
                ),
            },
        ],
        "related": ["pokemon-deals", "etb-deals", "ebay-pokemon-deals", "vinted-pokemon-deals", "cheap-pokemon-cards"],
    },
    "graded-pokemon-cards": {
        "title": "Graded Pokemon Cards | PSA and Beckett Deal Alerts",
        "meta_description": "Track graded Pokemon card deals, PSA slabs, Beckett cards, CGC listings and underpriced marketplace opportunities.",
        "h1": "Graded Pokemon Cards",
        "intro": (
            "Graded Pokemon cards are a major part of the collector market. "
            "PSA slabs, Beckett graded cards, CGC cards and other certified listings can vary widely in price depending on grade, language, set, popularity and demand. "
            "TCG Sniper Deals helps users discover fresh graded card listings from eBay and Vinted."
        ),
        "sections": [
            {
                "title": "PSA, Beckett and CGC listings",
                "text": (
                    "A graded card listing may include words like PSA, BGS, Beckett, CGC, slab, graded or certification details. "
                    "The same card can be listed with a clean English title, a local-language title or only a partial card number. "
                    "The live feed is designed to surface these listings quickly so users can inspect photos, grade, label, certification number and seller history."
                ),
            },
            {
                "title": "Pricing signals need context",
                "text": (
                    "A slab price can look attractive, but the grade and card version matter. "
                    "A PSA 10, PSA 9 and raw card should not be treated as the same product. "
                    "TCG Sniper Deals can help with faster discovery and pricing signals where available, but users should still verify condition, certification and market comparables before buying."
                ),
            },
            {
                "title": "Built for fast review",
                "text": (
                    "The paid VIP app keeps graded Pokemon opportunities inside a live stream with source labels, images and direct marketplace links. "
                    "This makes it easier to review new slabs as they appear instead of manually refreshing eBay and Vinted searches for PSA Charizard, graded Pikachu, vintage slabs or modern chase cards."
                ),
            },
        ],
        "related": ["pokemon-card-deals", "charizard-deals", "ebay-pokemon-deals", "vinted-pokemon-deals", "pokemon-deals"],
    },
    "vinted-pokemon-deals": {
        "title": "Pokemon Vinted Deals | Cheap Pokemon Card Alerts",
        "meta_description": "Track Pokemon Vinted deals, cheap Pokemon cards, bundles, ETBs and underpriced TCG listings.",
        "h1": "Pokemon Vinted Deals",
        "intro": (
            "Vinted can be a strong place to find cheap Pokemon cards, bundles and collection listings from casual sellers. "
            "Some sellers do not price every card against the full market, which can create opportunities for collectors and resellers. "
            "TCG Sniper Deals helps users see new Vinted Pokemon listings faster."
        ),
        "sections": [
            {
                "title": "Find underpriced Vinted listings",
                "text": (
                    "Vinted listings can be messy. A seller may write a title in French, Portuguese, Spanish or English, use only a Pokemon name, upload a binder photo or describe a group of cards as a lot. "
                    "Those imperfect listings can still be useful. "
                    "The system watches for Pokemon TCG signals and brings relevant listings into a live feed so users can inspect price, photos and seller rating quickly."
                ),
            },
            {
                "title": "Common Vinted opportunities",
                "text": (
                    "Vinted Pokemon opportunities may include cheap singles, mixed bundles, graded cards, ETBs, sealed products, booster packs and collection boxes. "
                    "The best listings often sell quickly because buyers are watching the same fresh marketplace flow. "
                    "A live alert system helps reduce the delay between a seller posting an item and a buyer seeing it."
                ),
            },
            {
                "title": "VIP app access",
                "text": (
                    "The paid app is where VIP users get the full Vinted stream, real-time updates and direct listing links. "
                    "The free Telegram channel can show limited examples, but it is not intended to expose the whole live feed. "
                    "That keeps the paid product focused on speed and first-look advantage."
                ),
            },
        ],
        "related": ["pokemon-deals", "pokemon-card-deals", "cheap-pokemon-cards", "charizard-deals", "etb-deals"],
    },
    "ebay-pokemon-deals": {
        "title": "Pokemon eBay Deals | Real-Time Card Alerts",
        "meta_description": "Find Pokemon eBay deals, underpriced cards, PSA slabs, sealed products and real-time TCG alerts.",
        "h1": "Pokemon eBay Deals",
        "intro": (
            "eBay is one of the biggest marketplaces for Pokemon cards, graded slabs, sealed boxes and rare collectibles. "
            "It also moves quickly, especially when a listing has a Buy It Now price that looks low compared with similar products. "
            "TCG Sniper Deals helps users monitor new eBay Pokemon listings and review them faster."
        ),
        "sections": [
            {
                "title": "Track eBay Pokemon listings",
                "text": (
                    "The system can surface eBay listings for raw cards, graded cards, PSA slabs, booster boxes, ETBs, sealed collections and vintage singles. "
                    "Useful listings can contain exact card names, card numbers, set names or only broader Pokemon TCG keywords. "
                    "A live feed helps users react to fresh listings instead of waiting for a manual search to be refreshed."
                ),
            },
            {
                "title": "Useful for flipping and collecting",
                "text": (
                    "Whether you are looking for cheap cards, graded Pokemon cards, Charizard deals or sealed products, timing matters. "
                    "Fast alerts can help collectors secure a wanted card and help resellers inspect a possible margin before other buyers act. "
                    "Users should still check seller feedback, shipping, condition, authenticity and whether the final price is still attractive."
                ),
            },
            {
                "title": "Pricing context",
                "text": (
                    "TCG Sniper Deals can use pricing signals where available, but marketplace data can be incomplete or blocked. "
                    "The app is built to keep working as a lightweight live opportunity stream even when deeper pricing checks need review. "
                    "That keeps the user experience fast while still supporting smarter deal detection over time."
                ),
            },
        ],
        "related": ["pokemon-deals", "pokemon-card-deals", "graded-pokemon-cards", "charizard-deals", "booster-box-deals"],
    },
    "cheap-pokemon-cards": {
        "title": "Cheap Pokemon Cards | Find Undervalued Deals",
        "meta_description": "Find cheap Pokemon cards, undervalued listings and real-time Pokemon TCG deal alerts from eBay and Vinted.",
        "h1": "Cheap Pokemon Cards",
        "intro": (
            "Finding cheap Pokemon cards online is not just about typing one search into a marketplace. "
            "The best opportunities usually appear and disappear quickly, often because sellers underprice a card, list a bundle casually or use an incomplete title. "
            "TCG Sniper Deals helps users watch for those fresh opportunities more efficiently."
        ),
        "sections": [
            {
                "title": "Undervalued Pokemon listings",
                "text": (
                    "Cheap does not always mean good value, but underpriced Pokemon listings can appear when a seller does not know the market, wants a fast sale or lists several cards together. "
                    "The live stream can show cards, bundles, ETBs, booster boxes and graded slabs as they are detected. "
                    "Users can then inspect the listing, compare prices and decide whether the opportunity is worth acting on."
                ),
            },
            {
                "title": "For collectors and resellers",
                "text": (
                    "Collectors may use the app to find cards for a personal binder or sealed collection. "
                    "Resellers may use it to identify possible spreads between listing price and market value. "
                    "In both cases, speed helps, but careful review is still important. Condition, language, seller rating and shipping can change the real value of a listing."
                ),
            },
            {
                "title": "From free alerts to VIP",
                "text": (
                    "The free Telegram channel gives limited public samples and promotional updates. "
                    "The full deal stream, direct links and real-time app access are part of the paid VIP product. "
                    "This setup gives new users a taste of the flow while keeping the strongest timing advantage inside the app."
                ),
            },
        ],
        "related": ["pokemon-deals", "pokemon-card-deals", "vinted-pokemon-deals", "ebay-pokemon-deals", "charizard-deals"],
    },
}
