import time
import random
import requests
from web3 import Web3
from eth_account import Account
from networks import NETWORKS
from settings import MIN_DELAY, MAX_DELAY, WITHDRAW_PERCENT, MIN_NATIVE_AMOUNT, MIN_USD_AMOUNT, GAS_SLIPPAGE_MULTIPLIER, FIXED_WITHDRAW_AMOUNT, SELECT_WITHDRAW_METHOD
from datetime import datetime
from requests.exceptions import HTTPError, ConnectionError

COINGECKO_URL = "https://api.coingecko.com/api/v3/simple/price?ids=ethereum,binancecoin,arbitrum,avalanche-2,polygon,optimism,base,zora,scroll,zk-sync-era,linea,op-bnb,fantom,mantle,usd-coin,tether,meme,altbase-token&vs_currencies=usd"

with open('wallets.txt', 'r') as f:
    private_keys = [line.strip() for line in f.readlines() if line.strip()]

with open('recipients.txt', 'r') as f:
    recipients = [line.strip() for line in f.readlines() if line.strip()]

if len(private_keys) != len(recipients):
    print("❌ Кількість гаманців і адрес не співпадає!")
    exit(1)

def safe_rpc_call(func, *args, **kwargs):
    retry = 0
    while retry < 5:
        try:
            return func(*args, **kwargs)
        except (HTTPError, ConnectionError) as e:
            wait = random.randint(5, 10)
            print(f"⏳ Rate limit або помилка з'єднання. Чекаємо {wait} сек...")
            time.sleep(wait)
            retry += 1
        except Exception as e:
            raise e
    raise Exception("🚫 Багато помилок під час запитів RPC")

def get_prices():
    response = requests.get(COINGECKO_URL)
    return response.json()

def build_gas_params(w3):
    try:
        latest_block = w3.eth.get_block('latest')
        if 'baseFeePerGas' in latest_block:
            base_fee = latest_block['baseFeePerGas']
            priority_fee = w3.to_wei(0.01, 'gwei')
            max_fee = base_fee + priority_fee
            return {
                'maxFeePerGas': int(max_fee),
                'maxPriorityFeePerGas': int(priority_fee)
            }
        else:
            return {'gasPrice': int(w3.eth.gas_price)}
    except:
        return {'gasPrice': int(w3.eth.gas_price)}

prices = get_prices()

start_time = time.time()
success_txs = []
total_usd = 0
total_token_sent = 0

print("\n🌐 Доступні мережі:")
networks_list = list(NETWORKS.keys())
for idx, net in enumerate(networks_list, 1):
    print(f"{idx}. {net}")

selected_net_idx = int(input("\nВведіть номер мережі: ")) - 1
selected_network_name = networks_list[selected_net_idx]
network = NETWORKS[selected_network_name]
w3 = Web3(Web3.HTTPProvider(network['rpc']))
chain_id = network['chain_id']

print(f"\n➡️ Ви вибрали мережу: {selected_network_name.upper()}")
print("\nТокени доступні для виводу:")
tokens_list = ['native'] + list(network['tokens'].keys())
for idx, token in enumerate(tokens_list, 1):
    print(f"{idx}. {token}")

selected_token_idx = int(input("\nВведіть номер токена: ")) - 1
selected_token = tokens_list[selected_token_idx]

# Додатково: правильний пошук токена у CoinGecko
coingecko_ids = {
    'native': network['native_symbol'].lower(),
    'usdc': 'usd-coin',
    'usdt': 'tether',
    'meme': 'meme',
    'alt': 'altbase-token'
}

def get_token_price(token):
    lookup = coingecko_ids.get(token.lower(), network['native_symbol'].lower())
    return prices.get(lookup, {}).get('usd', 0)

counter = 1

for pk, recipient in zip(private_keys, recipients):
    account = Account.from_key(pk)
    sender = account.address
    print(f"{counter}. ➡️ Обробка {sender} → {recipient}")
    counter += 1

    try:
        nonce = safe_rpc_call(w3.eth.get_transaction_count, sender)
        native_balance = safe_rpc_call(w3.eth.get_balance, sender)
        gas_params = build_gas_params(w3)

        dummy_tx = {
            'from': sender,
            'to': Web3.to_checksum_address(recipient),
            'value': 0,
            **gas_params
        }

        try:
            estimated_gas = safe_rpc_call(w3.eth.estimate_gas, dummy_tx)
        except Exception as e:
            print("⚠️ Недостатньо балансу для оцінки газу. Пропущено.")
            continue

        gas_limit = int(estimated_gas * GAS_SLIPPAGE_MULTIPLIER)
        gas_cost = (gas_params.get('maxFeePerGas') or gas_params.get('gasPrice')) * gas_limit

        if native_balance <= gas_cost:
            print("⚠️ Недостатньо балансу для покриття газу. Пропущено.")
            continue

        if selected_token == 'native':
            if SELECT_WITHDRAW_METHOD == 'percent':
                if WITHDRAW_PERCENT == 100:
                    sendable_balance = native_balance - gas_cost
                else:
                    available_balance = native_balance - gas_cost
                    sendable_balance = int(available_balance * (WITHDRAW_PERCENT / 100))
            elif SELECT_WITHDRAW_METHOD == 'fixed':
                sendable_balance = int(FIXED_WITHDRAW_AMOUNT * 1e18)
                if sendable_balance > (native_balance - gas_cost):
                    sendable_balance = native_balance - gas_cost

            if sendable_balance < MIN_NATIVE_AMOUNT * 1e18:
                print(f"⚠️ Недостатньо суми для виводу мінімум {MIN_NATIVE_AMOUNT} {network['native_symbol']}.")
                continue

            token_price = get_token_price('native')
            amount_usd = (sendable_balance / 1e18) * token_price

            print(f"📤 Відправляється: {(sendable_balance / 1e18):.6f} {network['native_symbol']} (~{amount_usd:.2f} USD)")

            tx = {
                'to': Web3.to_checksum_address(recipient),
                'value': int(sendable_balance),
                'gas': gas_limit,
                'nonce': nonce,
                'chainId': chain_id,
                **gas_params
            }

        else:
            token_address = Web3.to_checksum_address(network['tokens'][selected_token])
            contract = w3.eth.contract(address=token_address, abi=[
                {
                    "name": "transfer",
                    "type": "function",
                    "inputs": [
                        {"name": "_to", "type": "address"},
                        {"name": "_value", "type": "uint256"}
                    ],
                    "outputs": [{"name": "", "type": "bool"}],
                    "stateMutability": "nonpayable"
                },
                {
                    "name": "balanceOf",
                    "type": "function",
                    "inputs": [{"name": "_owner", "type": "address"}],
                    "outputs": [{"name": "balance", "type": "uint256"}],
                    "stateMutability": "view"
                }
            ])

            token_balance = safe_rpc_call(contract.functions.balanceOf(sender).call)

            if token_balance == 0:
                print("⚠️ Баланс токена = 0")
                continue

            token_price = get_token_price(selected_token)
            decimals = 6 if selected_token.lower() in ['usdc', 'usdt'] else 18
            amount_usd = (token_balance / (10 ** decimals)) * token_price

            if selected_token in ['USDT', 'USDC'] and (token_balance / (10 ** 6)) < MIN_USD_AMOUNT:
                print(f"⚠️ Мінімальний баланс для виводу {MIN_USD_AMOUNT} {selected_token}. Пропущено.")
                continue

            print(f"📤 Відправляється: {token_balance/(10**decimals):.6f} {selected_token} (~{amount_usd:.2f} USD)")

            tx = contract.functions.transfer(
                Web3.to_checksum_address(recipient), token_balance
            ).build_transaction({
                'from': sender,
                'nonce': nonce,
                'gas': gas_limit,
                'chainId': chain_id,
                **gas_params
            })

        signed_tx = w3.eth.account.sign_transaction(tx, private_key=pk)
        raw_tx = signed_tx.rawTransaction if hasattr(signed_tx, 'rawTransaction') else signed_tx.raw_transaction
        tx_hash = safe_rpc_call(w3.eth.send_raw_transaction, raw_tx)

        print(f"✅ Успішно! Tx: {w3.to_hex(tx_hash)}")
        success_txs.append((sender, recipient, w3.to_hex(tx_hash)))
        total_usd += amount_usd
        if selected_token == 'native':
            total_token_sent += sendable_balance / 1e18
        else:
            total_token_sent += token_balance / (10 ** decimals)

    except Exception as e:
        print(f"❌ Помилка: {e}")

    time.sleep(random.randint(MIN_DELAY, MAX_DELAY))

end_time = time.time()
minutes = int((end_time - start_time) // 60)
seconds = int((end_time - start_time) % 60)

print(f"\n🏁 Скрипт завершено!")
print(f"✅ Успішно відправлено {len(success_txs)} транзакцій.")
print(f"💵 Загальна сума виведення: {total_usd:.2f} USD")
if selected_token == 'native':
    print(f"🏦 Загальна кількість виведеного: {total_token_sent:.6f} {network['native_symbol']}")
else:
    print(f"🏦 Загальна кількість виведеного: {total_token_sent:.6f} {selected_token}")
print(f"🕒 Час роботи скрипта: {minutes} хв {seconds} сек")
