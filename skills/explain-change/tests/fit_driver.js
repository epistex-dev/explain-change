// Runs the lane fit (assets/ui/fit.js) on jobs read from stdin: [{orders, W, mk, gap, lo, hi}]; prints each result as JSON.
const F = require('../assets/ui/fit.js');
const jobs = JSON.parse(require('fs').readFileSync(0, 'utf8'));
process.stdout.write(JSON.stringify(jobs.map(j => F.fit(j.orders, j.W, j.mk, j.gap, j.lo, j.hi))));
