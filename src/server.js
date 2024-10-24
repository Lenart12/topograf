global.httpServer = new Promise((resolve) => {
  import('./index.js').then((index) => resolve(index.server.server));
});
  