// Executa os contratos do rincao-dados no ambiente explicitamente configurado.
const root = packet.root;
process.env.NODE_PATH = packet.dependencies + '/node_modules';
require('node:module').Module._initPaths();
const dotenv = require(root + '/node_modules/dotenv');
const mode = process.env.RINCAO_COMMERCE_MODE || 'test';
const production = mode === 'production';
const productionEnv = process.env.RINCAO_COMMERCE_RPC_ENV;
if (!production) dotenv.config({path: root + '/.env', quiet: true});
const env = production
  ? productionEnv && dotenv.config({path: productionEnv, processEnv: {}, quiet: true}).parsed
  : process.env;
const database = env?.POSTGRES_SISTEMA_DB || '';
const testDatabase = /_test$/i.test(database);
const allowedDatabase = production
  ? database && !testDatabase && database === process.env.RINCAO_COMMERCE_DATABASE_NAME
    && env.RINCAO_TICKET_API_USE_TEST_DB === 'false'
  : mode === 'test' && testDatabase && env.RINCAO_TICKET_API_USE_TEST_DB === 'true';
if (!allowedDatabase) {
  console.log(JSON.stringify({rpc_error: production ? 'production_database_mismatch' : 'test_database_required'}));
  process.exit(0);
}
const {Pool} = require(root + '/node_modules/pg');
const {PgCommerceRepository} = require(packet.build + '/modules/commerce/commerce.repository');
const schemas = require(packet.build + '/modules/commerce/commerce.schemas');
const pool = new Pool({host: env.POSTGRES_SISTEMA_HOST, port: Number(env.POSTGRES_SISTEMA_PORT),
  database: env.POSTGRES_SISTEMA_DB, user: env.POSTGRES_SISTEMA_USER,
  password: env.POSTGRES_SISTEMA_PASSWORD, max: 1, connectionTimeoutMillis: 5000,
  statement_timeout: 8000, ...(packet.operation === 'quote' ? {options: '-c default_transaction_read_only=on'} : {})});
(async () => {
  try {
    if (packet.payload.tenant_id !== env.RINCAO_COMMERCE_TENANT_ID || packet.payload.product_type === 'school_trip' || !Array.isArray(packet.payload.items) || packet.payload.items.some(item => item.ticketType === 'escola')) throw Error('invalid_scope');
    const repository = new PgCommerceRepository(pool, true);
    let result;
    if (packet.operation === 'quote') {
      if (packet.payload.product_type !== 'day_use' || !Array.isArray(packet.payload.items) || !packet.payload.items.length || packet.payload.items.some(item => !Number.isInteger(item.quantity) || item.quantity < 1 || item.quantity > 100 || !['padrao','promo'].includes(item.ticketType) || !['adult','child','exempt'].includes(item.ticketCategory) || !/^\d{4}-\d{2}-\d{2}$/.test(item.visitDate))) throw Error('invalid_quote');
      result = await repository.quoteDayUse(schemas.CommerceQuoteRequestSchema.parse(packet.payload));
    }
    else if (packet.operation === 'pending') result = await repository.createPendingOrder(schemas.CommerceCheckoutCreatedRequestSchema.parse(packet.payload));
    else if (packet.operation === 'approved') result = await repository.createApprovedOrder(schemas.CommerceWebhookRequestSchema.parse(packet.payload));
    else throw Error('invalid_operation');
    console.log(JSON.stringify(result));
  } catch (error) {
    console.log(JSON.stringify({rpc_error: error.code || 'commerce_contract_rejected'}));
  } finally { await pool.end(); }
})();
