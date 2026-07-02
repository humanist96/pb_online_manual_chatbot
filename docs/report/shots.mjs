import {chromium} from 'playwright-core';
import {pathToFileURL} from 'node:url';
const b = await chromium.launch({executablePath: process.argv[2], args:['--no-sandbox']});
const p = await b.newPage({viewport:{width:794, height:1123}});
await p.goto(pathToFileURL('out/report.html').href, {waitUntil:'networkidle'});
await p.evaluate(() => document.fonts.ready);
const pages = await p.locator('.page').all();
for (let i=0;i<pages.length;i++) await pages[i].screenshot({path:`out/pg${i+1}.png`});
await b.close(); console.log('shots:', pages.length);
