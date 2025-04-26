import time
import random
import requests
from web3 import Web3
from eth_account import Account
from networks import NETWORKS
from datetime import datetime
from requests.exceptions import HTTPError, ConnectionError

# ==== API для курсів токенів ====
COINGECKO_URL = "https://api.coingecko.com/api/v3/simple/price?ids=ethereum,binancecoin,arbitrum,avalanche-2,polygon,optimism,base,zora,scroll,zk-sync-era,linea,op-bnb&vs_currencies=usd"

# ==== Завантаження приватних ключів та адрес отримувачів ====
with open('wallets.txt', 'r') as f:
    private_keys = [line.strip() for line in f.readlines() if line.strip()]

with open('recipients.txt', 'r') as f:
    exchange_addresses = [line.strip() for line in f.readlines() if line.strip()]

if len(private_keys) != len(exchange_addresses):
    print("❌ Кількість гаманців і адрес не співпадає!")
    exit(1)

success_log = []
total_usd_sent = 0
total_token_sent = 0
successful_transactions = 0
start_time = datetime.now()

# ==== Функції ====

def fetch_token_prices():
    try:
        response = requests.get(COINGECKO_URL)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"❌ Помилка отримання цін токенів: {e}")
        return {}

def safe_rpc_call(func, *args, **kwargs):
    retries = 5
    for attempt in range(retries):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            if '429' in str(e) or 'Too Many Requests' in str(e):
                wait_time = random.randint(5, 10)
                print(f"⏳ Rate limit RPC. Чекати {wait_time} сек...")
                time.sleep(wait_time)
            else:
                raise e
    raise Exception("❌ Занадто багато спроб після 429 RPC")

# ==== Початок ====

prices = fetch_token_prices()

ERC20_ABI = [
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
]

print("\n🌐 Доступні мережі:")
networks_list = list(NETWORKS.keys())
for idx, net in enumerate(networks_list, 1):
    print(f"{idx}. {net}")

selected_net_idx = int(input("\nВведіть номер мережі: ")) - 1
selected_network_name = networks_list[selected_net_idx]
network = NETWORKS[selected_network_name]
w3 = Web3(Web3.HTTPProvider(network['rpc']))

print(f"\n➡️ Ви вибрали мережу: {selected_network_name.upper()}")
print("\nТокени:")
print("1. Native (" + network['native_symbol'] + ")")
tokens_list = list(network['tokens'].keys())
for idx, token in enumerate(tokens_list, 2):
    print(f"{idx}. {token}")

selected_token_idx = int(input("\nВведіть номер токена: "))

is_native = selected_token_idx == 1
selected_token = None if is_native else tokens_list[selected_token_idx - 2]

for pk, recipient in zip(private_keys, exchange_addresses):
    account = Account.from_key(pk)
    address = account.address

    print(f"\n➡️ Обробка {address} → {recipient}")

    try:
        native_balance = safe_rpc_call(w3.eth.get_balance, address)
        gas_price = safe_rpc_call(lambda: w3.eth.gas_price)

        if is_native:
            estimated_gas = safe_rpc_call(w3.eth.estimate_gas, {
                'to': Web3.to_checksum_address(recipient),
                'from': address,
                'value': 1
            })
            total_gas_cost = gas_price * estimated_gas * 1.2
            send_amount = native_balance - total_gas_cost
            min_send_amount = 0.0001 * 1e18

            if send_amount > min_send_amount:
                usd_value = send_amount * prices.get(network['native_symbol'].lower(), {}).get('usd', 0) / 1e18
                print(f"📤 Відправляється: {send_amount/1e18:.6f} {network['native_symbol']} (~{usd_value:.2f} USD)")
                tx = {
                    'to': Web3.to_checksum_address(recipient),
                    'value': int(send_amount),
                    'gas': int(estimated_gas * 1.2),
                    'gasPrice': gas_price,
                    'nonce': safe_rpc_call(w3.eth.get_transaction_count, address),
                    'chainId': network['chain_id']
                }
                signed_tx = w3.eth.account.sign_transaction(tx, private_key=pk)
                tx_hash = safe_rpc_call(w3.eth.send_raw_transaction, signed_tx.raw_transaction)
                print(f"✅ Відправлено нативний токен: {w3.to_hex(tx_hash)}")
                success_log.append(f"{selected_network_name} {address} → {recipient} Native: {w3.to_hex(tx_hash)}")
                total_usd_sent += usd_value
                total_token_sent += send_amount / 1e18
                successful_transactions += 1
                time.sleep(random.randint(10, 30))
            else:
                print(f"⚠️ Недостатньо коштів для безпечної відправки: {send_amount/1e18:.6f} {network['native_symbol']}")
        else:
            contract = w3.eth.contract(address=Web3.to_checksum_address(network['tokens'][selected_token]), abi=ERC20_ABI)
            token_balance = safe_rpc_call(contract.functions.balanceOf(address).call)

            if token_balance > 0:
                if selected_token in ['USDC', 'USDT'] and (token_balance / 10**6) < 0.1:
                    print(f"⚠️ Баланс менший 0.1 {selected_token}. Пропуск.")
                    continue
                elif selected_token.lower() == 'meme' and (token_balance / 10**18) < 100:
                    print(f"⚠️ Баланс менший 100 {selected_token}. Пропуск.")
                    continue

                estimated_gas = safe_rpc_call(contract.functions.transfer(Web3.to_checksum_address(recipient), token_balance).estimate_gas, {'from': address})
                total_gas_cost = gas_price * estimated_gas * 1.2

                if native_balance > total_gas_cost:
                    decimals = 6 if selected_token.lower() in ['usdc', 'usdt'] else 18
                    usd_value = token_balance / (10 ** decimals) * prices.get(network['native_symbol'].lower(), {}).get('usd', 0)
                    print(f"📤 Відправляється: {token_balance/(10**decimals):.6f} токенів (~{usd_value:.2f} USD)")
                    tx = contract.functions.transfer(
                        Web3.to_checksum_address(recipient), token_balance
                    ).build_transaction({
                        'from': address,
                        'nonce': safe_rpc_call(w3.eth.get_transaction_count, address),
                        'gas': int(estimated_gas * 1.2),
                        'gasPrice': gas_price,
                        'chainId': network['chain_id']
                    })
                    signed_tx = w3.eth.account.sign_transaction(tx, private_key=pk)
                    tx_hash = safe_rpc_call(w3.eth.send_raw_transaction, signed_tx.raw_transaction)
                    print(f"✅ Відправлено токени: {w3.to_hex(tx_hash)}")
                    success_log.append(f"{selected_network_name} {address} → {recipient}: {w3.to_hex(tx_hash)}")
                    total_usd_sent += usd_value
                    total_token_sent += token_balance / (10**decimals)
                    successful_transactions += 1
                    time.sleep(random.randint(10, 30))
                else:
                    print(f"⚠️ Недостатньо балансу для покриття газу. Пропущено.")
            else:
                print(f"⚠️ Баланс токена = 0")
                continue

    except Exception as e:
        print(f"❌ Помилка: {e}")

# ==== Запис результатів ====

with open('success_log.txt', 'w', encoding='utf-8') as f:
    for line in success_log:
        f.write(line + '\n')

end_time = datetime.now()
run_time = end_time - start_time
minutes, seconds = divmod(run_time.seconds, 60)

print("\n🏁 Скрипт завершено!")
print(f"✅ Успішно відправлено {successful_transactions} транзакцій.")
print(f"💵 Загальна сума виведення: {total_usd_sent:.2f} USD")
if is_native:
    print(f"🏦 Загальна кількість виведеного {network['native_symbol']}: {total_token_sent:.6f} {network['native_symbol']}")
else:
    print(f"🏦 Загальна кількість виведеного {selected_token}: {total_token_sent:.6f} {selected_token}")
print(f"🕒 Час роботи скрипта: {minutes} хв {seconds} сек")
