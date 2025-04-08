import { env } from './env';
import { launchHttpServer } from './http-server';
import { launchTelegram } from './telegram';

function start() {
  switch (env.RUN_MODE) {
    case 'http-server':
      launchHttpServer();
      break;
    case 'telegram':
      launchTelegram();
      break;
    default:
      throw new Error(`invalid run mode: ${env.RUN_MODE}`);
  }
}

start();
