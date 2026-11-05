// Runs the page's edge router on boxes read from stdin (JSON {boxes, obstacles, edges, W, H}); prints its routes as JSON (zones optional).
const R = require('../assets/ui/route.js');
const input = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const jobs = Array.isArray(input) ? input : [input];
process.stdout.write(JSON.stringify(jobs.map(j => R.route(j.boxes, j.obstacles || [], j.edges, j.W, j.H, j.zones || []))));
