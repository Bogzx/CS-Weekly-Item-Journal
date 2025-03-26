const https = require("https");
const parser = require("node-html-parser");
const fs = require("fs");
const { URLSearchParams } = require("url");

getSite();

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
    let skins = [];

    let req = https.request(options, (res) => {
        res.on('data', d => {
            response += d.toString();
        });

        res.on('end', () => {
            try {
                let root = parser.parse(response);
                console.log("HTML parsed successfully");
                
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
                            
                            // Generate Steam Market API URL for price data - using Factory New quality
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
                
                console.log(`Scraped ${skins.length} skins`);
                
                // Save to file
                const jsonData = JSON.stringify(skins, null, 2); // Pretty print with 2 spaces
                /*fs.writeFile("cs_skins.json", jsonData, (err) => {
                    if (err) {
                        console.error("Error writing file:", err);
                    } else {
                        console.log("Successfully saved skins data to cs_skins.json");
                    }
                });*/
                
                // Also save as CSV
                const csvHeader = "Collection,Weapon,Skin,Quality,Steam Market API URL\n";
                const csvRows = skins.map(skin => 
                    `"${skin.collection || ''}","${skin.weapon || ''}","${skin.skin || ''}","${skin.quality || ''}","${skin.marketUrl || ''}"`
                ).join("\n");
                
                fs.writeFile("cs_skins.csv", csvHeader + csvRows, (err) => {
                    if (err) {
                        console.error("Error writing CSV file:", err);
                    } else {
                        console.log("Successfully saved skins data to cs_skins.csv");
                    }
                });
                
            } catch (error) {
                console.error("Error parsing or processing data:", error);
            }
        });
    });

    req.on('error', (error) => {
        console.error("Error making request:", error);
    });

    req.end();
}

/**
 * create_cs_skins.js
 * 
 * Description:
 * This script fetches CS:GO/CS2 skin data from the Steam Market and generates a CSV file
 * with information including weapon type, skin name, quality, and Market API URLs.
 * 
 * Requirements:
 * - Node.js (v12.0.0 or higher)
 * - Required packages: 
 *   - axios (npm install axios)
 *   - papaparse (npm install papaparse)
 * 
 * Usage:
 * node create_cs_skins.js [options]
 * 
 * Options:
 * --output <path>     Path where the CSV file will be saved (default: cs_skins.csv)
 * --batch-size <num>  Number of items to fetch per API request (default: 50)
 * --max-items <num>   Maximum number of items to fetch (default: 5000)
 * --delay <ms>        Delay between API requests in milliseconds (default: 1000)
 * 
 * Examples:
 * node create_cs_skins.js
 * node create_cs_skins.js --output my_skins.csv --max-items 1000
 * node create_cs_skins.js --batch-size 20 --delay 2000
 * 
 * Notes:
 * - Steam has rate limits, be careful with batch-size and delay settings
 * - The script may take several minutes to complete depending on settings
 * - The generated CSV will have columns: Collection, Weapon, Skin, Quality, Steam Market API URL
 */