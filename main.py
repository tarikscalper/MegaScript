import time
import random
import requests
from web3 import Web3
from eth_account import Account
from networks import NETWORKS
from datetime import datetime

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
successful_transactions = 0
start_time = datetime.now()

# ==== Функції ====

def safe_call(func, *args, **kwargs):
    retry_count = 0
    while retry_count < 5:
        try:
            return func(*args, **kwargs)
        except (requests.exceptions.HTTPError, requests.exceptions.ConnectionError) as e:
            if '429' in str(e):
                wait_time = random.randint(10, 20)
                print(f"   ⏳ Rate limit. Чекати {wait_time} сек...")
                time.sleep(wait_time)
                retry_count += 1
            else:
                raise e
    raise Exception("   ❌ Занадто багато спроб після 429")

def fetch_token_prices():
    try:
        response = requests.get(COINGECKO_URL)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"❌ Помилка отримання цін токенів: {e}")
        return {}

# ==== Початок ====

prices = fetch_token_prices()

ERC20_ABI = [
    {
        "constant": False,
        "inputs": [
            {"name": "_to", "type": "address"},
            {"name": "_value", "type": "uint256"}
        ],
        "name": "transfer",
        "outputs": [{"name": "", "type": "bool"}],
        "type": "function"
    },
    {
        "constant": True,
        "inputs": [{"name": "_owner", "type": "address"}],
        "outputs": [{"name": "balance", "type": "uint256"}],
        "type": "function"
    }
]

# ==== Вибір мережі ====

print("\n🌐 Доступні мережі:")
networks_list = list(NETWORKS.keys())
for idx, net in enumerate(networks_list, 1):
    print(f"{idx}. {net}")

selected_net_idx = int(input("\nВведіть номер мережі: ")) - 1
selected_network_name = networks_list[selected_net_idx]
network = NETWORKS[selected_network_name]
w3 = Web3(Web3.HTTPProvider(network['rpc']))

# ==== Вибір токена ====

print(f"\n➡️ Ви вибрали мережу: {selected_network_name.upper()}")
print("\nТокени:")
print("1. Native (" + network['native_symbol'] + ")")
tokens_list = list(network['tokens'].keys())
for idx, token in enumerate(tokens_list, 2):
    print(f"{idx}. {token}")

selected_token_idx = int(input("\nВведіть номер токена: "))

is_native = selected_token_idx == 1
selected_token = None if is_native else tokens_list[selected_token_idx - 2]

# ==== Початок обробки ====

for pk, recipient in zip(private_keys, exchange_addresses):
    account = Account.from_key(pk)
    address = account.address

    print(f"\n➡️ Обробка {address} → {recipient}")

    try:
        native_balance = safe_call(w3.eth.get_balance, address)
        gas_price = safe_call(lambda: w3.eth.gas_price)

        if is_native:
            estimated_gas = safe_call(w3.eth.estimate_gas, {
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
                    'nonce': safe_call(w3.eth.get_transaction_count, address),
                    'chainId': network['chain_id']
                }
                signed_tx = w3.eth.account.sign_transaction(tx, private_key=pk)
                tx_hash = safe_call(w3.eth.send_raw_transaction, signed_tx.raw_transaction)
                print(f"✅ Відправлено нативний токен: {w3.to_hex(tx_hash)}")
                success_log.append(f"{selected_network_name} {address} → {recipient} Native: {w3.to_hex(tx_hash)}")
                total_usd_sent += usd_value
                successful_transactions += 1
            else:
                print(f"⚠️ Недостатньо коштів для безпечної відправки: {send_amount/1e18:.6f} {network['native_symbol']}")
        else:
            contract = w3.eth.contract(address=Web3.to_checksum_address(network['tokens'][selected_token]), abi=ERC20_ABI)
            token_balance = safe_call(contract.functions.balanceOf(address).call)

            if token_balance > 0:
                estimated_gas = safe_call(contract.functions.transfer(Web3.to_checksum_address(recipient), token_balance).estimate_gas, {'from': address})
                total_gas_cost = gas_price * estimated_gas * 1.2

                if native_balance > total_gas_cost:
                    usd_value = token_balance / (10 ** 6) * prices.get(network['native_symbol'].lower(), {}).get('usd', 0)
                    print(f"📤 Відправляється: {token_balance/1e6:.6f} {selected_token} (~{usd_value:.2f} USD)")
                    tx = contract.functions.transfer(
                        Web3.to_checksum_address(recipient), token_balance
                    ).build_transaction({
                        'from': address,
                        'nonce': safe_call(w3.eth.get_transaction_count, address),
                        'gas': int(estimated_gas * 1.2),
                        'gasPrice': gas_price,
                        'chainId': network['chain_id']
                    })
                    signed_tx = w3.eth.account.sign_transaction(tx, private_key=pk)
                    tx_hash = safe_call(w3.eth.send_raw_transaction, signed_tx.raw_transaction)
                    print(f"✅ Відправлено {selected_token}: {w3.to_hex(tx_hash)}")
                    success_log.append(f"{selected_network_name} {address} → {recipient} {selected_token}: {w3.to_hex(tx_hash)}")
                    total_usd_sent += usd_value
                    successful_transactions += 1
                else:
                    print(f"⚠️ Недостатньо балансу для покриття газу. Пропущено.")
            else:
                print(f"⚠️ Баланс {selected_token} = 0")

        time.sleep(random.randint(10, 30))

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
print(f"🕒 Час роботи скрипта: {minutes} хв {seconds} сек")
