const https = require("https");
const parser = require("node-html-parser");
const fs = require("fs");

const OUTPUT_FILE = "cs_skins.csv";

if (require.main === module) {
    getSite();
}

/**
 * Extract skins from the wiki's Skins/List page.
 *
 * Collections are the <h4> headings and each .wikitable that follows is that
 * collection's skins, so the two lists are paired by index.
 */
function parseSkins(html) {
    let root = parser.parse(html);
    let skins = [];

    let collectionNames = [];
    root.querySelectorAll("h4").forEach(el => {
        if (el.querySelector('a') && el.querySelector('a').childNodes[0]) {
            collectionNames.push(el.querySelector('a').childNodes[0].rawText);
        }
    });

    console.log(`Found ${collectionNames.length} collections`);
    let k = 0;

    root.querySelectorAll(".wikitable").forEach(table => {
        table.querySelectorAll('tr').forEach((row, idx) => {
            if (idx === 0) {
                return;
            }

            try {
                let skin = {};

                if (k < collectionNames.length) {
                    skin.collection = collectionNames[k];
                } else {
                    skin.collection = "Unknown Collection";
                }

                if (row.querySelector('a') && row.querySelector('a').childNodes[0]) {
                    skin.weapon = row.querySelector('a').childNodes[0].rawText;
                }

                if (row.querySelectorAll('span')[0] && row.querySelectorAll('span')[0].childNodes[0]) {
                    skin.skin = row.querySelectorAll('span')[0].childNodes[0].rawText;
                }

                if (row.querySelectorAll('span')[1] && row.querySelectorAll('span')[1].childNodes[0]) {
                    skin.quality = row.querySelectorAll('span')[1].childNodes[0].rawText;
                }

                // Price URL for one wear; populate_database.py rewrites it per wear
                if (skin.weapon && skin.skin) {
                    const marketName = `${skin.weapon} | ${skin.skin} (Minimal Wear)`;
                    const encodedName = encodeURIComponent(marketName);
                    skin.marketUrl = `https://steamcommunity.com/market/priceoverview/?appid=730&market_hash_name=${encodedName}`;
                } else {
                    skin.marketUrl = "";
                }

                skins.push(skin);
            } catch (rowError) {
                console.error("Error processing row:", rowError);
            }
        });

        k++;
    });

    return skins;
}

/** Quote a CSV field, doubling any embedded quotes. */
function csvField(value) {
    return `"${String(value || '').replace(/"/g, '""')}"`;
}

function toCsv(skins) {
    const csvHeader = "Collection,Weapon,Skin,Quality,Steam Market API URL\n";
    const csvRows = skins.map(skin =>
        [skin.collection, skin.weapon, skin.skin, skin.quality, skin.marketUrl].map(csvField).join(",")
    ).join("\n");
    return csvHeader + csvRows;
}

function fail(message) {
    // Leave any existing cs_skins.csv alone and exit non-zero. This used to
    // parse whatever came back -- including a 403 challenge page -- find 0
    // skins, overwrite the CSV with just a header and report success.
    console.error(message);
    process.exitCode = 1;
}

function getSite() {
    console.log("Fetching site...");
    let options = {
        hostname: "counterstrike.fandom.com",
        path: "/wiki/Skins/List",
        method: "GET",
        headers: {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
    }

    let response = "";

    let req = https.request(options, (res) => {
        res.on('data', d => {
            response += d.toString();
        });

        res.on('end', () => {
            if (res.statusCode !== 200) {
                return fail(`Wiki returned HTTP ${res.statusCode}; not writing ${OUTPUT_FILE}.`);
            }

            let skins;
            try {
                skins = parseSkins(response);
            } catch (error) {
                return fail(`Error parsing or processing data: ${error}`);
            }

            console.log(`Scraped ${skins.length} skins`);
            if (skins.length === 0) {
                return fail(`No skins found; the page layout may have changed. Not writing ${OUTPUT_FILE}.`);
            }

            fs.writeFile(OUTPUT_FILE, toCsv(skins), (err) => {
                if (err) {
                    fail(`Error writing CSV file: ${err}`);
                } else {
                    console.log(`Successfully saved skins data to ${OUTPUT_FILE}`);
                }
            });
        });
    });

    req.on('error', (error) => {
        fail(`Error making request: ${error}`);
    });

    req.end();
}

module.exports = { parseSkins, toCsv, csvField };

/**
 * create_cs_skins.js
 *
 * Description:
 * Scrapes the Counter-Strike fandom wiki's Skins/List page and writes
 * cs_skins.csv (Collection, Weapon, Skin, Quality, Steam Market API URL) to
 * the current directory. It takes no options.
 *
 * Requirements:
 * - Node.js 18+
 * - `npm install` in the repository root (installs node-html-parser)
 *
 * Usage:
 * node Src/DB/create_cs_skins.js
 *
 * Notes:
 * - Exits with status 1 and leaves any existing cs_skins.csv untouched if the
 *   wiki does not answer 200 or no skins are found.
 */
