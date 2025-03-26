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
                fs.writeFile("cs_skins.json", jsonData, (err) => {
                    if (err) {
                        console.error("Error writing file:", err);
                    } else {
                        console.log("Successfully saved skins data to cs_skins.json");
                    }
                });
                
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