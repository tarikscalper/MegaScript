# Затримка між транзакціями (в секундах)
MIN_DELAY = 10
MAX_DELAY = 20

# Мінімальна сума нативного токена для виводу (у токені)
MIN_NATIVE_AMOUNT = 0.0001

# Мінімальна сума в USD для токенів USDT/USDC
MIN_USD_AMOUNT = 0.1

# Відсоток виводу (працює, якщо обрано режим 'percent')
WITHDRAW_PERCENT = 99

# Фіксована сума виводу в нативному токені (працює, якщо обрано режим 'fixed')
FIXED_WITHDRAW_AMOUNT = 0.01  # наприклад 0.01 ETH або MATIC і т.д.

# Метод виводу: 'percent' або 'fixed'
SELECT_WITHDRAW_METHOD = 'percent'

# Коефіцієнт запасу на газ (наприклад 1.2 = 20% запас)
GAS_SLIPPAGE_MULTIPLIER = 1.2