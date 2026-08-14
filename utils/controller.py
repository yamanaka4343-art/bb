import uuid
import aiosqlite
from PayPayPy import PayPay

class PayPayController:
    @staticmethod
    async def initialize():
        async with aiosqlite.connect("./data/paypay.db") as db:
            await db.execute("CREATE TABLE IF NOT EXISTS paypay(user_id TEXT, access_token TEXT, device_uuid TEXT, client_uuid TEXT)")
            await db.commit()

    @staticmethod
    async def create_data(user_id, access_token, device_uuid, client_uuid):
        async with aiosqlite.connect("./data/paypay.db") as db:
            await db.execute("INSERT INTO paypay(user_id, access_token, device_uuid, client_uuid) VALUES (?, ?, ?, ?)", (str(user_id), access_token, device_uuid, client_uuid,))
            await db.commit()

    @staticmethod
    async def update_data(user_id, access_token):
        async with aiosqlite.connect("./data/paypay.db") as db:
            await db.execute("UPDATE paypay SET access_token=? WHERE user_id=?", (access_token, str(user_id),))
            await db.commit()

    @staticmethod
    async def delete_data(user_id):
        async with aiosqlite.connect("./data/paypay.db") as db:
            await db.execute("DELETE FROM paypay WHERE user_id=?", (str(user_id),))
            await db.commit()

    @staticmethod
    async def get_data_from_user_id(user_id):
        async with aiosqlite.connect("./data/paypay.db") as db:
            cursor = await db.execute("SELECT * FROM paypay WHERE user_id=?", (str(user_id),))
            rows = await cursor.fetchall()
            if len(rows) == 0:
                return None, None, None
            row = rows[0]
            return row[1], row[2], row[3]
        
    @staticmethod
    async def get_client(user_id):
        access_token, device_uuid, client_uuid = await PayPayController.get_data_from_user_id(user_id)
        if access_token is None:
            return None
        
        paypay = PayPay(
            access_token=access_token,
            device_uuid=device_uuid,
            client_uuid=client_uuid
        )
        return paypay

class MachineController:
    @staticmethod
    async def initialize():
        async with aiosqlite.connect("./data/machine.db") as db:
            await db.execute("CREATE TABLE IF NOT EXISTS machine(machine_uuid TEXT, name TEXT, user_id TEXT, message_id TEXT)")
            try:
                await db.execute("ALTER TABLE machine ADD COLUMN description TEXT")
            except:
                pass
            await db.commit()

    @staticmethod
    async def create_data(machine_uuid, name, user_id, message_id, description=""):
        async with aiosqlite.connect("./data/machine.db") as db:
            await db.execute("INSERT INTO machine(machine_uuid, name, user_id, message_id, description) VALUES(?, ?, ?, ?, ?)", (machine_uuid, name, str(user_id), str(message_id), description))
            await db.commit()

    @staticmethod
    async def update_info(machine_uuid, name, description):
        async with aiosqlite.connect("./data/machine.db") as db:
            await db.execute("UPDATE machine SET name=?, description=? WHERE machine_uuid=?", (name, description, machine_uuid))
            await db.commit()

    @staticmethod
    async def update_data(machine_uuid, message_id):
        async with aiosqlite.connect("./data/machine.db") as db:
            await db.execute("UPDATE machine SET message_id=? WHERE machine_uuid=?", (str(message_id), machine_uuid,))
            await db.commit()

    @staticmethod
    async def get_machines_from_user_id(user_id):
        async with aiosqlite.connect("./data/machine.db") as db:
            cursor = await db.execute("SELECT * FROM machine WHERE user_id=?", (str(user_id),))
            rows = await cursor.fetchall()
            return rows

    @staticmethod
    async def get_machine_from_machine_uuid(machine_uuid):
        async with aiosqlite.connect("./data/machine.db") as db:
            cursor = await db.execute("SELECT * FROM machine WHERE machine_uuid=?", (machine_uuid,))
            row = await cursor.fetchone()
            if row is None:
                return None, None, None, None, None
            return row[0], row[1], row[2], row[3], row[4] if len(row) > 4 else ""
        
    @staticmethod
    async def get_machine_from_message_id(message_id):
        async with aiosqlite.connect("./data/machine.db") as db:
            cursor = await db.execute("SELECT * FROM machine WHERE message_id=?", (str(message_id),))
            row = await cursor.fetchone()
            if row is None:
                return None, None, None, None, None
            return row[0], row[1], row[2], row[3], row[4] if len(row) > 4 else ""
        
    @staticmethod
    async def delete_data(machine_uuid):
        async with aiosqlite.connect("./data/machine.db") as db:
            await db.execute("DELETE FROM machine WHERE machine_uuid=?", (machine_uuid,))
            await db.commit()

class ProductController:
    @staticmethod
    async def initialize():
        async with aiosqlite.connect("./data/product.db") as db:
            await db.execute("CREATE TABLE IF NOT EXISTS product(product_uuid TEXT, name TEXT, price TEXT, machine_uuid TEXT)")
            try:
                await db.execute("ALTER TABLE product ADD COLUMN description TEXT")
            except:
                pass
            await db.commit()

    @staticmethod
    async def create_data(product_uuid, name, price, machine_uuid, description=""):
        async with aiosqlite.connect("./data/product.db") as db:
            try:
                await db.execute("INSERT INTO product(product_uuid, name, price, machine_uuid, description) VALUES(?, ?, ?, ?, ?)", (product_uuid, name, str(price), machine_uuid, description))
            except:
                await db.execute("INSERT INTO product(product_uuid, name, price, machine_uuid) VALUES(?, ?, ?, ?)", (product_uuid, name, str(price), machine_uuid))
            await db.commit()

    @staticmethod
    async def get_product_from_product_uuid(product_uuid):
        async with aiosqlite.connect("./data/product.db") as db:
            cursor = await db.execute("SELECT * FROM product WHERE product_uuid=?", (product_uuid,))
            row = await cursor.fetchone()
            if row is None:
                return None, None, None, None, None
            return row[0], row[1], row[2], row[3], row[4] if len(row) > 4 else ""
        
    @staticmethod
    async def get_products_from_machine_uuid(machine_uuid):
        async with aiosqlite.connect("./data/product.db") as db:
            cursor = await db.execute("SELECT * FROM product WHERE machine_uuid=?", (machine_uuid,))
            rows = await cursor.fetchall()
            return rows
        
    @staticmethod
    async def delete_data(product_uuid):
        async with aiosqlite.connect("./data/product.db") as db:
            await db.execute("DELETE FROM product WHERE product_uuid=?", (product_uuid,))
            await db.commit()

    @staticmethod
    async def update_data(product_uuid, name, price, description=""):
        async with aiosqlite.connect("./data/product.db") as db:
            try:
                await db.execute("UPDATE product SET name=?, price=?, description=? WHERE product_uuid=?", (name, str(price), description, product_uuid))
            except:
                await db.execute("UPDATE product SET name=?, price=? WHERE product_uuid=?", (name, str(price), product_uuid))
            await db.commit()

class StockController:
    @staticmethod
    async def initialize():
        async with aiosqlite.connect("./data/stock.db") as db:
            await db.execute("CREATE TABLE IF NOT EXISTS stock(stock_uuid TEXT, content TEXT, product_uuid TEXT)")
            await db.commit()

    @staticmethod
    async def add_stock(content, product_uuid):
        stock_uuid = str(uuid.uuid4())
        async with aiosqlite.connect("./data/stock.db") as db:
            await db.execute("INSERT INTO stock(stock_uuid, content, product_uuid) VALUES(?, ?, ?)", (stock_uuid, content, product_uuid,))
            await db.commit()

    @staticmethod
    async def get_stock(product_uuid):
        async with aiosqlite.connect("./data/stock.db") as db:
            cursor = await db.execute("SELECT * FROM stock WHERE product_uuid=?", (product_uuid,))
            rows = await cursor.fetchall()
            if len(rows) == 0:
                return None, None, None
            row = rows[0]
            return row[0], row[1], row[2]
        
    @staticmethod
    async def get_stocks(product_uuid):
        async with aiosqlite.connect("./data/stock.db") as db:
            cursor = await db.execute("SELECT * FROM stock WHERE product_uuid=?", (product_uuid,))
            rows = await cursor.fetchall()
            return rows
        
    @staticmethod
    async def remove_stock(stock_uuid):
        async with aiosqlite.connect("./data/stock.db") as db:
            await db.execute("DELETE FROM stock WHERE stock_uuid=?", (stock_uuid,))
            await db.commit()

class LogController:
    @staticmethod
    async def initialize():
        async with aiosqlite.connect("./data/log.db") as db:
            await db.execute("CREATE TABLE IF NOT EXISTS log(machine_uuid TEXT, guild_id TEXT, channel_id TEXT)")
            try:
                await db.execute("ALTER TABLE log ADD COLUMN admin_channel_id TEXT")
            except:
                pass
            await db.commit()

    @staticmethod
    async def create_data(machine_uuid, guild_id, channel_id, admin_channel_id=""):
        async with aiosqlite.connect("./data/log.db") as db:
            try:
                await db.execute("INSERT INTO log(machine_uuid, guild_id, channel_id, admin_channel_id) VALUES(?, ?, ?, ?)", (machine_uuid, str(guild_id), str(channel_id), str(admin_channel_id)))
            except:
                await db.execute("INSERT INTO log(machine_uuid, guild_id, channel_id) VALUES(?, ?, ?)", (machine_uuid, str(guild_id), str(channel_id)))
            await db.commit()

    @staticmethod
    async def update_data(machine_uuid, guild_id, channel_id, admin_channel_id):
        async with aiosqlite.connect("./data/log.db") as db:
            cursor = await db.execute("SELECT * FROM log WHERE machine_uuid=?", (machine_uuid,))
            if await cursor.fetchone():
                try:
                    await db.execute("UPDATE log SET guild_id=?, channel_id=?, admin_channel_id=? WHERE machine_uuid=?", (str(guild_id), str(channel_id) if channel_id else "", str(admin_channel_id) if admin_channel_id else "", machine_uuid))
                except:
                    await db.execute("UPDATE log SET guild_id=?, channel_id=? WHERE machine_uuid=?", (str(guild_id), str(channel_id) if channel_id else "", machine_uuid))
            else:
                try:
                    await db.execute("INSERT INTO log(machine_uuid, guild_id, channel_id, admin_channel_id) VALUES(?, ?, ?, ?)", (machine_uuid, str(guild_id), str(channel_id) if channel_id else "", str(admin_channel_id) if admin_channel_id else ""))
                except:
                    pass
            await db.commit()

    @staticmethod
    async def get_data(machine_uuid):
        async with aiosqlite.connect("./data/log.db") as db:
            cursor = await db.execute("SELECT * FROM log WHERE machine_uuid=?", (machine_uuid,))
            row = await cursor.fetchone()
            if row is None:
                return None, None, None, None
            return row[0], row[1], row[2], row[3] if len(row) > 3 else None

class CouponController:
    @staticmethod
    async def initialize():
        async with aiosqlite.connect("./data/coupon.db") as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS coupons (
                    code TEXT PRIMARY KEY,
                    discount_percent INTEGER,
                    usage_limit INTEGER,
                    usage_count INTEGER DEFAULT 0,
                    target_type TEXT, -- 'all', 'machine', 'product'
                    target_id TEXT
                )
            """)
            await db.commit()

    @staticmethod
    async def create_coupon(code, discount_percent, usage_limit, target_type='all', target_id=None):
        async with aiosqlite.connect("./data/coupon.db") as db:
            await db.execute("INSERT INTO coupons (code, discount_percent, usage_limit, target_type, target_id) VALUES (?, ?, ?, ?, ?)",
                             (code, discount_percent, usage_limit, target_type, target_id))
            await db.commit()

    @staticmethod
    async def get_coupon(code):
        async with aiosqlite.connect("./data/coupon.db") as db:
            cursor = await db.execute("SELECT * FROM coupons WHERE code=?", (code,))
            return await cursor.fetchone()

    @staticmethod
    async def use_coupon(code):
        async with aiosqlite.connect("./data/coupon.db") as db:
            await db.execute("UPDATE coupons SET usage_count = usage_count + 1 WHERE code=?", (code,))
            await db.commit()

    @staticmethod
    async def delete_coupon(code):
        async with aiosqlite.connect("./data/coupon.db") as db:
            await db.execute("DELETE FROM coupons WHERE code=?", (code,))
            await db.commit()
    
    @staticmethod
    async def get_all_coupons():
        async with aiosqlite.connect("./data/coupon.db") as db:
            cursor = await db.execute("SELECT * FROM coupons")
            return await cursor.fetchall()
