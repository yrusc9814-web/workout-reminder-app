'use strict';
// Prefer an explicitly supplied node_modules directory, otherwise normal Node resolution.
const path = require('path');
const external = process.env.WORKOUT_NODE_MODULES;
try {
  module.exports = require(external ? path.join(external, 'jsdom') : 'jsdom');
} catch (error) {
  throw new Error('jsdom is required: use existing project node_modules or set WORKOUT_NODE_MODULES to an existing node_modules directory. Tests do not install dependencies. ' + error.message);
}
