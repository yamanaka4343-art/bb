# 互換性パッチ
import collections
import collections.abc
collections.Mapping = collections.abc.Mapping
collections.MutableMapping = collections.abc.MutableMapping
collections.Sequence = collections.abc.Sequence

import discord
from discord import app_commands
from discord.ext import commands
import asyncio
import io
import os
import uuid
import traceback
import aiosqlite
from datetime import datetime
from typing import Optional

from PayPayPy import PayPay
# 整理されたすべてのデータベースコントローラーをインポート
from utils.controller import PayPayController, MachineController, ProductController, StockController, LogController, CouponController, MachineLogSettings, NotifyController

cb = '`' * 3
proxy = os.getenv("PAYPAY_PROXY", "")

async def send_error(interaction: discord.Interaction, message: str):
    embed = discord.Embed(title="❌ エラー", description=f"{cb}yaml\n{message}\n{cb}", color=discord.Color.red())
    try:
        if interaction.response.is_done():
            await interaction.followup.send(embed=embed, ephemeral=True)
        else:
            await interaction.response.send_message(embed=embed, ephemeral=True)
    except discord.errors.NotFound:
        pass

# ==========================================
# Modals
# ==========================================
class ProductEditModal(discord.ui.Modal):
    def __init__(self, product_uuid, current_name, current_price, current_desc):
        super().__init__(title="商品の編集", timeout=None)
        self.product_uuid = product_uuid
        
        self.name_input = discord.ui.TextInput(
            label="商品名",
            default=current_name,
            style=discord.TextStyle.short,
            required=True,
            max_length=100
        )
        self.add_item(self.name_input)

        self.price_input = discord.ui.TextInput(
            label="価格 (半角数字のみ)",
            default=str(current_price),
            style=discord.TextStyle.short,
            required=True,
            max_length=10
        )
        self.add_item(self.price_input)

        self.desc_input = discord.ui.TextInput(
            label="商品の説明",
            default=current_desc,
            style=discord.TextStyle.paragraph,
            required=False,
            max_length=500
        )
        self.add_item(self.desc_input)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            if not self.price_input.value.isdigit():
                await send_error(interaction, "価格には数字以外入力できません。")
                return

            new_name = self.name_input.value
            new_price = int(self.price_input.value)
            new_desc = self.desc_input.value or "説明なし"

            await ProductController.update_data(self.product_uuid, new_name, new_price, new_desc)

            success_embed = discord.Embed(title="✅ 編集完了", description=f"{cb}yaml\n商品の情報を更新しました。\n{cb}", color=discord.Color.green())
            success_embed.add_field(name="新しい名前", value=f"{cb}yaml\n{new_name}\n{cb}", inline=True)
            success_embed.add_field(name="新しい価格", value=f"{cb}yaml\n{new_price}円\n{cb}", inline=True)
            
            await interaction.edit_original_response(embed=success_embed)
        except Exception as e:
            traceback.print_exc()
            await send_error(interaction, f"更新中にエラーが発生しました: {e}")

# ==========================================
# PayPay Login
# ==========================================
class PayPayLoginStartModal(discord.ui.Modal):
    def __init__(self):
        super().__init__(title="PayPayログイン - 資格情報", timeout=None)
        self.phone = discord.ui.TextInput(label="電話番号 (ハイフン無し)", style=discord.TextStyle.short, min_length=11, max_length=11, required=True)
        self.add_item(self.phone)
        self.password = discord.ui.TextInput(label="パスワード", style=discord.TextStyle.short, max_length=32, required=True)
        self.add_item(self.password)

    async def on_submit(self, interaction: discord.Interaction):
        access_token, device_uuid, client_uuid = await PayPayController.get_data_from_user_id(interaction.user.id)
        if access_token is None:
            device_uuid = str(uuid.uuid4())
            client_uuid = str(uuid.uuid4())

        paypay = PayPay(device_uuid=device_uuid, client_uuid=client_uuid, proxy=proxy if proxy else None)

        processing_embed = discord.Embed(title="🔄 処理中", description=f"{cb}yaml\n現在ログイン処理を実行中です、お待ちください...\n{cb}", color=discord.Color.yellow())
        await interaction.response.send_message(embed=processing_embed, ephemeral=True)
        
        coro = asyncio.to_thread(paypay.login, self.phone.value, self.password.value)
        try:
            login_result = await coro
        except Exception as e:
            error_str = str(e)
            if "S3104" in error_str:
                await send_error(interaction, "PayPayへのログインに失敗しました (S3104)。\n・情報が間違っていないか確認してください。")
            else:
                await send_error(interaction, f"PayPayへのログイン処理中にエラーが発生しました。\n詳細: {error_str}")
            return
        
        if login_result and login_result.get("header", {}).get("resultCode") == "S0000":
            current_token = paypay.headers.get("Authorization", "").replace("Bearer ", "")
            await PayPayController.update_data(interaction.user.id, current_token)
            success_embed = discord.Embed(title="✅ 成功", description=f"{cb}yaml\nPayPayへのログインに成功しました。\n{cb}", color=discord.Color.green())
            await interaction.edit_original_response(embed=success_embed)
            return
            
        try:
            otp_reference_id = login_result["error"]["otpReferenceId"]
        except:
            otp_reference_id = None
        
        if not otp_reference_id:
            await send_error(interaction, "OTPリファレンスIDの取得に失敗しました。")
            return

        success_embed = discord.Embed(title="📱 処理続行", description=f"{cb}yaml\nOTPの送信に成功しました。\nSMSで受信したコードを入力して続行してください。\n{cb}", color=discord.Color.green())
        await interaction.edit_original_response(embed=success_embed, view=PayPayLoginOTPButton(paypay, otp_reference_id))
        
class PayPayLoginOTPButton(discord.ui.View):
    def __init__(self, paypay, otp_reference_id):
        super().__init__(timeout=None)
        self.paypay = paypay
        self.otp_reference_id = otp_reference_id

    @discord.ui.button(label="OTP認証", style=discord.ButtonStyle.green)
    async def otp_verify(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(PayPayLoginOTPModal(self.paypay, self.otp_reference_id))

class PayPayLoginOTPModal(discord.ui.Modal):
    def __init__(self, paypay, otp_reference_id):
        super().__init__(title="PayPayログイン - OTP", timeout=None)
        self.paypay = paypay
        self.otp_reference_id = otp_reference_id
        self.otp_code = discord.ui.TextInput(label="SMSで届いた認証コード (数字)", style=discord.TextStyle.short, required=True)
        self.add_item(self.otp_code)

    async def on_submit(self, interaction: discord.Interaction):
        processing_embed = discord.Embed(title="🔄 処理中", description=f"{cb}yaml\n現在ログイン処理を続行中です、お待ちください...\n{cb}", color=discord.Color.yellow())
        await interaction.response.edit_message(embed=processing_embed, view=None)

        coro = asyncio.to_thread(self.paypay.login_otp, self.otp_reference_id, self.otp_code.value)
        try:
            await coro
        except:
            await send_error(interaction, "PayPayへのOTP認証処理中にエラーが発生しました。")
            return
        
        try:
            current_token = self.paypay.headers.get("Authorization", "").replace("Bearer ", "")
        except:
            current_token = None

        access_token, device_uuid, client_uuid = await PayPayController.get_data_from_user_id(interaction.user.id)
        if access_token is None:
            await PayPayController.create_data(interaction.user.id, current_token, self.paypay.device_uuid, self.paypay.client_uuid)
        else:
            await PayPayController.update_data(interaction.user.id, current_token)

        success_embed = discord.Embed(title="✅ 成功", description=f"{cb}yaml\nPayPayへのログインに成功しました。\n{cb}", color=discord.Color.green())
        await interaction.edit_original_response(embed=success_embed)

class PayPayLoginStartView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
    @discord.ui.button(label="🔑 ログイン情報を入力する", style=discord.ButtonStyle.primary, custom_id="paypay_login_start_btn")
    async def start_login(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(PayPayLoginStartModal())

# ==========================================
# セレクト・削除等のビュー群
# ==========================================
class MachineDeleteSelect(discord.ui.Select):
    def __init__(self, machines):
        options = [discord.SelectOption(label=m[1], description=f"UUID: {m[0]}", value=m[0]) for m in machines][:25]
        super().__init__(placeholder="削除する自販機を選択してください", options=options)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        machine_uuid = self.values[0]
        await MachineController.delete_data(machine_uuid)
        embed = discord.Embed(title="✅ 成功", description=f"{cb}yaml\n選択された自販機を完全に削除しました。\n{cb}", color=discord.Color.green())
        await interaction.edit_original_response(embed=embed, view=None)

class MachineDeleteView(discord.ui.View):
    def __init__(self, machines):
        super().__init__(timeout=180)
        self.add_item(MachineDeleteSelect(machines))

class MachineEditSelect(discord.ui.Select):
    def __init__(self, machines, name, description, pub_id, adm_id):
        options = [discord.SelectOption(label=m[1], description=f"UUID: {m[0]}", value=m[0]) for m in machines][:25]
        super().__init__(placeholder="編集する自販機を選択してください", options=options)
        self.edit_name = name
        self.edit_description = description
        self.pub_id = pub_id
        self.adm_id = adm_id

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        machine_uuid = self.values[0]
        _uuid, cur_name, _, _, cur_desc = await MachineController.get_machine_from_machine_uuid(machine_uuid)
        
        new_name = self.edit_name if self.edit_name is not None else cur_name
        new_desc = self.edit_description if self.edit_description is not None else cur_desc
        await MachineController.update_info(machine_uuid, new_name, new_desc)
        
        # サーバーごとの実績チャンネル設定を更新
        log_data = await MachineLogSettings.get_log_channels(machine_uuid, interaction.guild_id)
        cur_pub = log_data[0] if log_data else 0
        cur_adm = log_data[1] if log_data else 0
            
        new_pub = self.pub_id if self.pub_id is not None else cur_pub
        new_adm = self.adm_id if self.adm_id is not None else cur_adm
        await MachineLogSettings.set_log_channels(machine_uuid, interaction.guild_id, new_pub, new_adm)
        
        embed = discord.Embed(title="✅ 成功", description=f"{cb}yaml\n自販機の設定を更新しました。\n※パネルに反映させるには再度 /machine summon を実行してください。\n{cb}", color=discord.Color.green())
        await interaction.edit_original_response(embed=embed, view=None)

class MachineEditView(discord.ui.View):
    def __init__(self, machines, name, description, pub_id, adm_id):
        super().__init__(timeout=180)
        self.add_item(MachineEditSelect(machines, name, description, pub_id, adm_id))

class MachineSummonSelect(discord.ui.Select):
    def __init__(self, machines, bot):
        options = [discord.SelectOption(label=m[1], description=f"UUID: {m[0]}", value=m[0]) for m in machines][:25]
        super().__init__(placeholder="設置する自販機を選択してください", options=options)
        self.bot = bot

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        machine_uuid = self.values[0]
        _uuid, name, _, _, desc = await MachineController.get_machine_from_machine_uuid(machine_uuid)
        rows = await ProductController.get_products_from_machine_uuid(machine_uuid)
        
        embed = discord.Embed(title=f"🏪 {name}", description=f"{cb}yaml\n{desc}\n{cb}" if desc else "", color=discord.Color.purple())
        for row in rows:
            p_desc = row[4] if len(row) > 4 and row[4] else "説明なし"
            embed.add_field(name=row[1], value=f"{cb}yaml\n価格：{row[2]}円\n説明：{p_desc}\n{cb}", inline=False)
            
        machine_msg = await interaction.channel.send(embed=embed, view=InfoButton(self.bot))
        await MachineController.update_data(machine_uuid, machine_msg.id)

        success_embed = discord.Embed(title="✅ 成功", description=f"{cb}yaml\n自販機を設置しました。\n{cb}", color=discord.Color.green())
        await interaction.edit_original_response(embed=success_embed, view=None)

class MachineSummonView(discord.ui.View):
    def __init__(self, machines, bot):
        super().__init__(timeout=180)
        self.add_item(MachineSummonSelect(machines, bot))

class ProductCreateMachineSelect(discord.ui.Select):
    def __init__(self, machines, name, price, description):
        options = [discord.SelectOption(label=m[1], description=f"UUID: {m[0]}", value=m[0]) for m in machines][:25]
        super().__init__(placeholder="商品を作成する自販機を選択してください", options=options)
        self.p_name = name
        self.p_price = price
        self.p_desc = description

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        machine_uuid = self.values[0]
        new_uuid = str(uuid.uuid4())
        await ProductController.create_data(new_uuid, self.p_name, self.p_price, machine_uuid, self.p_desc)

        embed = discord.Embed(title="✅ 成功", description=f"{cb}yaml\n商品を作成しました。\n{cb}", color=discord.Color.green())
        embed.add_field(name="名前", value=f"{cb}yaml\n{self.p_name}\n{cb}", inline=False)
        embed.add_field(name="UUID", value=f"{cb}yaml\n{new_uuid}\n{cb}", inline=False)
        await interaction.edit_original_response(embed=embed, view=None)

class ProductCreateMachineView(discord.ui.View):
    def __init__(self, machines, name, price, description):
        super().__init__(timeout=180)
        self.add_item(ProductCreateMachineSelect(machines, name, price, description))

class MachineSelectForProductAction(discord.ui.Select):
    def __init__(self, machines, action, **kwargs):
        options = [discord.SelectOption(label=m[1], description=f"UUID: {m[0]}", value=m[0]) for m in machines][:25]
        super().__init__(placeholder="対象の自販機を選択してください", options=options)
        self.action = action
        self.kwargs = kwargs

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        machine_uuid = self.values[0]
        products = await ProductController.get_products_from_machine_uuid(machine_uuid)
        
        if not products:
            embed = discord.Embed(title="❌ エラー", description=f"{cb}yaml\nこの自販機には商品が登録されていません。\n{cb}", color=discord.Color.red())
            await interaction.edit_original_response(embed=embed, view=None)
            return
            
        embed = discord.Embed(title="📦 商品選択", description=f"{cb}yaml\n対象の商品を選択してください。\n{cb}", color=discord.Color.blue())
        view = ProductActionView(products, self.action, **self.kwargs)
        await interaction.edit_original_response(embed=embed, view=view)

class MachineSelectForProductView(discord.ui.View):
    def __init__(self, machines, action, **kwargs):
        super().__init__(timeout=180)
        self.add_item(MachineSelectForProductAction(machines, action, **kwargs))

class ProductActionSelect(discord.ui.Select):
    def __init__(self, products, action, **kwargs):
        options = [discord.SelectOption(label=p[1], description=f"価格: {p[2]}円", value=p[0]) for p in products][:25]
        super().__init__(placeholder="商品を選択してください", options=options)
        self.action = action
        self.kwargs = kwargs

    async def callback(self, interaction: discord.Interaction):
        product_uuid = self.values[0]
        
        if self.action == "edit":
            _uuid, cur_name, cur_price, _m_uuid, cur_desc = await ProductController.get_product_from_product_uuid(product_uuid)
            await interaction.response.send_modal(ProductEditModal(product_uuid, cur_name, cur_price, cur_desc))
            await interaction.edit_original_response(view=None)
            
        elif self.action == "delete":
            await interaction.response.defer(ephemeral=True)
            await ProductController.delete_data(product_uuid)
            embed = discord.Embed(title="✅ 成功", description=f"{cb}yaml\n商品を削除しました。\n{cb}", color=discord.Color.green())
            await interaction.edit_original_response(embed=embed, view=None)
            
        elif self.action == "restock":
            _uuid, name, _, _, _ = await ProductController.get_product_from_product_uuid(product_uuid)
            bot = self.kwargs.get("bot")
            user = interaction.user
            await interaction.response.send_modal(
                ProductRestockModal(product_uuid, name, user, bot, interaction.guild_id)
            )
            await interaction.edit_original_response(view=None)
            
        elif self.action == "takestock":
            await interaction.response.defer(ephemeral=True)
            all_take = self.kwargs.get("all_take")
            if all_take:
                stocks = await StockController.get_stocks(product_uuid)
                stock_contents = []
                for stock in stocks:
                    await StockController.remove_stock(stock[0])
                    stock_contents.append(stock[1])

                stock_text = "\n".join(stock_contents)
                buffer = io.BytesIO(stock_text.encode("utf-8"))
                buffer.seek(0)
                embed = discord.Embed(title="✅ 成功", description=f"{cb}yaml\nすべての在庫を取り出しました。\n{cb}", color=discord.Color.green())
                await interaction.edit_original_response(embed=embed, view=None, attachments=[discord.File(buffer, filename="stocks.txt")])
            else:
                try:
                    stock_uuid, content, _ = await StockController.get_stock(product_uuid)
                    await StockController.remove_stock(stock_uuid)
                    embed = discord.Embed(title="✅ 成功", description=f"{cb}yaml\n在庫を取り出しました。\n{cb}", color=discord.Color.green())
                    embed.add_field(name="在庫内容", value=f"{cb}yaml\n{content}\n{cb}", inline=False)
                    await interaction.edit_original_response(embed=embed, view=None)
                except Exception:
                    await interaction.edit_original_response(view=None)
                    await send_error(interaction, "取り出せる在庫がありません。")

class ProductActionView(discord.ui.View):
    def __init__(self, products, action, **kwargs):
        super().__init__(timeout=180)
        self.add_item(ProductActionSelect(products, action, **kwargs))

# ==========================================
# Restock Modal
# ==========================================
class ProductRestockModal(discord.ui.Modal):
    def __init__(self, product_uuid, product_name, user, bot, guild_id):
        super().__init__(title="在庫追加", timeout=None)
        self.product_uuid = product_uuid
        self.product_name = product_name
        self.user = user
        self.bot = bot
        self.guild_id = guild_id
        self.contents = discord.ui.TextInput(label="商品", style=discord.TextStyle.paragraph, placeholder="改行して在庫を追加", required=True)
        self.add_item(self.contents)

    async def on_submit(self, interaction: discord.Interaction):
        processing_embed = discord.Embed(title="🔄 処理中", description=f"{cb}yaml\n現在在庫を追加しています、お待ちください...\n{cb}", color=discord.Color.yellow())
        await interaction.response.send_message(embed=processing_embed, ephemeral=True)

        contents_list = [content.strip() for content in self.contents.value.split("\n") if content.strip()]
        for content in contents_list:
            await StockController.add_stock(content, self.product_uuid)

        notify_data = await NotifyController.get_notify(self.guild_id)
        if notify_data:
            channel_id, role_id = notify_data
            channel = self.bot.get_channel(channel_id)
            if channel:
                try:
                    notification_embed = discord.Embed(title="🔔 在庫追加通知", description=f"{self.user.mention} が在庫を追加しました", color=discord.Color.blue())
                    notification_embed.add_field(name="商品名", value=f"{cb}yaml\n{self.product_name}\n{cb}", inline=False)
                    notification_embed.add_field(name="追加数", value=f"{cb}yaml\n{len(contents_list)}個\n{cb}", inline=True)
                    notification_embed.set_footer(text=f"追加者: {self.user.name}", icon_url=self.user.display_avatar.url)
                    
                    mention_content = f"<@&{role_id}>" if role_id and role_id != 0 else None
                    
                    await channel.send(content=mention_content, embed=notification_embed, allowed_mentions=discord.AllowedMentions(users=True, roles=True))
                except Exception as e:
                    print(f"通知の送信に失敗しました: {e}")

        success_embed = discord.Embed(title="✅ 成功", description=f"{cb}yaml\n{self.product_name} の在庫を {len(contents_list)} 個追加しました。\n{cb}", color=discord.Color.green())
        await interaction.edit_original_response(embed=success_embed)

# ==========================================
# Info & Buy (複数購入 & クーポン対応)
# ==========================================
async def complete_process(interaction: discord.Interaction, product_uuid: str, log_channel: Optional[discord.TextChannel], admin_log_channel: Optional[discord.TextChannel], quantity: int, total_price: int, used_coupon: str = None):
    processing_embed = discord.Embed(title="🔄 処理中", description=f"{cb}yaml\n現在処理中です、このままお待ちください。\n購入個数: {quantity}個\n{cb}", color=discord.Color.yellow())
    await interaction.edit_original_response(embed=processing_embed, view=None)

    try:
        _product_uuid, name, price, machine_uuid, _desc = await ProductController.get_product_from_product_uuid(product_uuid)
        all_stocks = await StockController.get_stocks(product_uuid)
        
        if len(all_stocks) < quantity:
            raise Exception("在庫が不足しました。")

        products = []
        for i in range(quantity):
            stock_uuid, content, _ = all_stocks[i]
            products.append(content)
            await StockController.remove_stock(stock_uuid)

        async with aiosqlite.connect("./data/product.db") as db:
            try:
                await db.execute("UPDATE product SET sales = COALESCE(sales, 0) + ? WHERE product_uuid=?", (quantity, product_uuid))
                await db.commit()
            except Exception as e:
                print(f"Sales update error: {e}")

        product_content = "\n".join([content.strip() for content in products])
        success_embed = discord.Embed(title="✅ 購入完了", description=f"{cb}yaml\n注文に成功しました。\n{cb}", color=discord.Color.green())
        success_embed.add_field(name="購入個数", value=f"{cb}yaml\n{quantity}個\n{cb}", inline=False)
        success_embed.add_field(name="支払金額", value=f"{cb}yaml\n{total_price}円\n{cb}", inline=False)
        if used_coupon:
            success_embed.add_field(name="適用クーポン", value=f"{cb}yaml\n{used_coupon}\n{cb}", inline=False)

        dm_sent = False
        try:
            panel_embed = discord.Embed(title="🛍️ 購入情報", color=discord.Color.green())
            panel_embed.add_field(name="商品名", value=f"{cb}yaml\n{name}\n{cb}", inline=False)
            panel_embed.add_field(name="購入個数", value=f"{cb}yaml\n{quantity}個\n{cb}", inline=False)
            panel_embed.add_field(name="支払金額", value=f"{cb}yaml\n{total_price}円\n{cb}", inline=True)
            
            file_buffer = io.BytesIO(product_content.encode("utf-8"))
            file_buffer.seek(0)
            await interaction.user.send(embed=panel_embed, file=discord.File(fp=file_buffer, filename=f"{name}.txt"))
            dm_sent = True
        except:
            pass

        if dm_sent:
            success_embed.add_field(name="DM送信", value=f"{cb}yaml\nBotからのDMに商品が送信されました。\n{cb}", inline=False)
        else:
            success_embed.add_field(name="DM送信", value=f"{cb}diff\n- DMの送信に失敗しました。\n- DMを許可しているか確認してください。\n{cb}", inline=False)

        await interaction.edit_original_response(embed=success_embed, view=None)

        if log_channel is not None:
            pub_embed = discord.Embed(title=f"🛍️ 購入実績", color=discord.Color.gold())
            pub_embed.add_field(name="購入者", value=f"{cb}yaml\n{interaction.user.name}\n{cb}", inline=False)
            pub_embed.add_field(name="商品名", value=f"{cb}yaml\n{name}\n{cb}", inline=True)
            pub_embed.add_field(name="個数", value=f"{cb}yaml\n{quantity}個\n{cb}", inline=True)
            pub_embed.add_field(name="支払金額", value=f"{cb}yaml\n{total_price}円\n{cb}", inline=False)
            asyncio.create_task(log_channel.send(embed=pub_embed))

        if admin_log_channel is not None:
            adm_embed = discord.Embed(title=f"📝 管理者用ログ", color=discord.Color.dark_red())
            adm_embed.add_field(name="購入者詳細", value=f"{cb}yaml\n{interaction.user.name} ({interaction.user.id})\n{cb}", inline=False)
            adm_embed.add_field(name="商品名", value=f"{cb}yaml\n{name}\n{cb}", inline=True)
            adm_embed.add_field(name="個数", value=f"{cb}yaml\n{quantity}個\n{cb}", inline=True)
            adm_embed.add_field(name="支払金額", value=f"{cb}yaml\n{total_price}円\n{cb}", inline=False)
            if used_coupon:
                adm_embed.add_field(name="クーポン", value=f"{cb}yaml\n{used_coupon}\n{cb}", inline=False)
            file_buffer_log = io.BytesIO(product_content.encode("utf-8"))
            file_buffer_log.seek(0)
            asyncio.create_task(admin_log_channel.send(embed=adm_embed, file=discord.File(fp=file_buffer_log, filename=f"{name}_log.txt")))

    except Exception as e:
        traceback.print_exc()
        await send_error(interaction, f"購入処理中にエラーが発生しました: {e}")

class BuyPaymentModal(discord.ui.Modal):
    def __init__(self, paypay, product_uuid, product_price, machine_uuid, log_channel, admin_log_channel):
        super().__init__(title="決済情報の入力", timeout=None)
        self.paypay = paypay
        self.product_uuid = product_uuid
        self.product_price = int(product_price)
        self.machine_uuid = machine_uuid
        self.log_channel = log_channel
        self.admin_log_channel = admin_log_channel

        self.quantity = discord.ui.TextInput(label="購入個数", style=discord.TextStyle.short, default="1", min_length=1, max_length=3, required=True)
        self.add_item(self.quantity)
        self.coupon_code = discord.ui.TextInput(label="クーポンコード (ない場合は空欄)", style=discord.TextStyle.short, required=False, max_length=50)
        self.add_item(self.coupon_code)
        self.paypay_link = discord.ui.TextInput(label="PayPayリンク", placeholder="https://pay.paypay.ne.jp/xxxx", required=True)
        self.add_item(self.paypay_link)
        self.paypay_passcode = discord.ui.TextInput(label="PayPayパスコード", placeholder="0000", min_length=4, max_length=4, required=False)
        self.add_item(self.paypay_passcode)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            if not self.quantity.value.isdigit() or int(self.quantity.value) <= 0:
                await send_error(interaction, "購入個数は1以上の数字を入力してください。")
                return

            quantity = int(self.quantity.value)
            stocks = await StockController.get_stocks(self.product_uuid)
            if len(stocks) < quantity:
                await send_error(interaction, f"在庫不足です (在庫: {len(stocks)}個)")
                return

            discount = 0
            used_coupon = None
            if self.coupon_code.value:
                coupon = await CouponController.get_coupon(self.coupon_code.value)
                if not coupon:
                    await send_error(interaction, "無効なクーポンコードです。")
                    return
                if coupon[2] > 0 and coupon[3] >= coupon[2]:
                    await send_error(interaction, "このクーポンは使用上限に達しています。")
                    return
                
                c_type = coupon[4]
                c_target = coupon[5]
                if c_type == "machine" and c_target != self.machine_uuid:
                    await send_error(interaction, "このクーポンはこの自販機では使用できません。")
                    return
                elif c_type == "product" and c_target != self.product_uuid:
                    await send_error(interaction, "このクーポンはこの商品では使用できません。")
                    return
                
                discount = coupon[1]
                used_coupon = coupon[0]

            total_price = int(self.product_price * quantity * (100 - discount) / 100)
            if total_price < 0: total_price = 0

            link_val = self.paypay_link.value
            verification_code = link_val.split("/")[-1] if "/" in link_val else link_val

            check_result = await asyncio.to_thread(self.paypay.get_link, verification_code)
            res_payload = check_result.get("payload", {})
            amount = res_payload.get("pendingP2PInfo", {}).get("amount") or res_payload.get("amount")
            order_status = res_payload.get("orderStatus")

            if int(amount) != total_price or order_status != 'PENDING':
                await send_error(interaction, f"金額不一致または使用済みのリンクです。\n必要金額: {total_price}円 (割引適用後)")
                return

            passcode = None if self.paypay_passcode.value == "" else self.paypay_passcode.value
            try:
                api_res = await asyncio.to_thread(self.paypay.accept_link, verification_code, passcode)
                if api_res.get("header", {}).get("resultCode") == "S0000":
                    if used_coupon:
                        await CouponController.use_coupon(used_coupon)
                    await complete_process(interaction, self.product_uuid, self.log_channel, self.admin_log_channel, quantity, total_price, used_coupon)
                else:
                    err_msg = api_res.get('header', {}).get('resultMessage', '詳細不明')
                    await send_error(interaction, f"PayPayの受け取りに失敗しました: {err_msg}")
            except Exception as e:
                await send_error(interaction, f"PayPayエラー: {e}")
                
        except Exception as e:
            traceback.print_exc()
            await send_error(interaction, f"エラーが発生しました: {e}")

# ==========================================
# Free Product Modal (無料商品取得用)
# ==========================================
class BuyFreeProductModal(discord.ui.Modal):
    def __init__(self, product_uuid, machine_uuid, log_channel, admin_log_channel):
        super().__init__(title="無料商品の取得", timeout=None)
        self.product_uuid = product_uuid
        self.machine_uuid = machine_uuid
        self.log_channel = log_channel
        self.admin_log_channel = admin_log_channel

        self.quantity = discord.ui.TextInput(
            label="取得個数", 
            style=discord.TextStyle.short, 
            default="1", 
            min_length=1, 
            max_length=3, 
            required=True
        )
        self.add_item(self.quantity)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            if not self.quantity.value.isdigit() or int(self.quantity.value) <= 0:
                await send_error(interaction, "取得個数は1以上の数字を入力してください。")
                return

            quantity = int(self.quantity.value)
            stocks = await StockController.get_stocks(self.product_uuid)
            if len(stocks) < quantity:
                await send_error(interaction, f"在庫不足です (在庫: {len(stocks)}個)")
                return

            await complete_process(interaction, self.product_uuid, self.log_channel, self.admin_log_channel, quantity, 0, None)
                
        except Exception as e:
            traceback.print_exc()
            await send_error(interaction, f"エラーが発生しました: {e}")

class BuyProductSelect(discord.ui.Select):
    def __init__(self, paypay, machine_uuid, options, log_channel, admin_log_channel):
        super().__init__(placeholder="購入する商品を選択", options=options)
        self.paypay = paypay
        self.machine_uuid = machine_uuid
        self.log_channel = log_channel
        self.admin_log_channel = admin_log_channel

    async def callback(self, interaction: discord.Interaction):
        values = self.values[0].split("::")
        product_uuid = values[0]
        product_price = int(values[1])
        if product_price == 0:
            await interaction.response.send_modal(BuyFreeProductModal(product_uuid, self.machine_uuid, self.log_channel, self.admin_log_channel))
        else:
            await interaction.response.send_modal(BuyPaymentModal(self.paypay, product_uuid, product_price, self.machine_uuid, self.log_channel, self.admin_log_channel))

class BuyProductSelectView(discord.ui.View):
    def __init__(self, paypay, machine_uuid, options, log_channel, admin_log_channel):
        super().__init__(timeout=None)
        self.add_item(BuyProductSelect(paypay, machine_uuid, options, log_channel, admin_log_channel))

class InfoButton(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(label="🛒購入する", style=discord.ButtonStyle.green, custom_id="buy_btn")
    async def buy(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        try:
            machine_uuid, name, user_id, message_id, _desc = await MachineController.get_machine_from_message_id(interaction.message.id)
            if not machine_uuid:
                await send_error(interaction, "自販機データの取得に失敗しました。")
                return

            log_data, paypay_data, rows = await asyncio.gather(
                MachineLogSettings.get_log_channels(machine_uuid, interaction.guild_id),
                PayPayController.get_data_from_user_id(user_id),
                ProductController.get_products_from_machine_uuid(machine_uuid)
            )
            
            public_channel_id, admin_channel_id = log_data if log_data else (None, None)
            access_token, device_uuid, client_uuid = paypay_data if paypay_data else (None, None, None)

            log_channel = None
            admin_log_channel = None
            guild = interaction.guild
            if guild:
                if public_channel_id:
                    log_channel = guild.get_channel(int(public_channel_id))
                if admin_channel_id:
                    admin_log_channel = guild.get_channel(int(admin_channel_id))

            if access_token is None:
                await send_error(interaction, "この自販機のPayPayアカウントが登録されていません。")
                return

            paypay = PayPay(access_token, device_uuid, client_uuid, proxy if proxy else None)

            options = []
            stock_tasks = [StockController.get_stocks(row[0]) for row in rows]
            if stock_tasks:
                stocks_list = await asyncio.gather(*stock_tasks)
                for i, row in enumerate(rows):
                    stock = len(stocks_list[i])
                    desc_text = row[4] if len(row) > 4 and row[4] else "説明なし"
                    options.append(discord.SelectOption(label=row[1][:100], description=f"在庫:{stock}個 | 価格:{row[2]}円 | {desc_text}"[:100], value=f"{row[0]}::{row[2]}"))
            
            if not options:
                await send_error(interaction, "現在販売されている商品はありません。")
                return

            embed = discord.Embed(title="🛒 商品選択", description=f"{cb}yaml\n購入する商品を選択してください。\n{cb}", color=discord.Color.yellow())
            await interaction.followup.send(embed=embed, view=BuyProductSelectView(paypay, machine_uuid, options, log_channel, admin_log_channel), ephemeral=True)
        except Exception as e:
            traceback.print_exc()
            await send_error(interaction, f"システムエラーが発生しました: {e}")

    @discord.ui.button(label="📦在庫・販売数確認", style=discord.ButtonStyle.primary, custom_id="stock_btn")
    async def stock(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        try:
            machine_uuid, name, user_id, message_id, _desc = await MachineController.get_machine_from_message_id(interaction.message.id)
            rows = await ProductController.get_products_from_machine_uuid(machine_uuid)
            if not rows:
                await send_error(interaction, "商品が登録されていません。")
                return
                
            sales_dict = {}
            async with aiosqlite.connect('./data/product.db') as db:
                cursor = await db.execute("SELECT product_uuid, sales FROM product WHERE machine_uuid=?", (machine_uuid,))
                sales_data = await cursor.fetchall()
                sales_dict = {r[0]: (r[1] if len(r) > 1 and r[1] is not None else 0) for r in sales_data}

            stock_tasks = [StockController.get_stocks(row[0]) for row in rows]
            stocks_list = await asyncio.gather(*stock_tasks)
            
            embed = discord.Embed(title="📦 自販機在庫・販売数確認", color=discord.Color.blue())
            for i, row in enumerate(rows):
                p_uuid = row[0]
                p_name = row[1]
                sales_count = sales_dict.get(p_uuid, 0)
                stock_count = len(stocks_list[i])
                embed.add_field(name=p_name, value=f"{cb}yaml\n在庫数：{stock_count} 個\n販売数：{sales_count} 回\n{cb}", inline=False)
            await interaction.followup.send(embed=embed, ephemeral=True)
        except Exception as e:
            traceback.print_exc()
            await send_error(interaction, f"エラーが発生しました: {e}")

# ==========================================
# Groups
# ==========================================
class PayPayGroup(app_commands.Group):
    def __init__(self, bot):
        super().__init__(name="paypay", description="PayPay設定コマンド")
        self.bot = bot

    @app_commands.command(name="login", description="PayPayにログインを実行します")
    @app_commands.default_permissions(administrator=True)
    async def login(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        embed = discord.Embed(title="🔐 PayPayログイン", description=f"{cb}yaml\n下のボタンを押して入力画面を開いてください。\n{cb}", color=discord.Color.blue())
        await interaction.followup.send(embed=embed, view=PayPayLoginStartView(), ephemeral=True)

    @app_commands.command(name="logout", description="PayPayからログアウトを行います")
    @app_commands.default_permissions(administrator=True)
    async def logout(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await PayPayController.delete_data(interaction.user.id)
        embed = discord.Embed(title="✅ 成功", description=f"{cb}yaml\nPayPayアカウントからのログアウトに成功しました。\n{cb}", color=discord.Color.green())
        await interaction.followup.send(embed=embed, ephemeral=True)

class MachineGroup(app_commands.Group):
    def __init__(self, bot):
        super().__init__(name="machine", description="自販機管理コマンド")
        self.bot = bot

    @app_commands.command(name="create", description="自販機を作成します")
    @app_commands.describe(public_log_channel="実績用ログ(txtなし)", admin_log_channel="管理者用ログ(txtあり)")
    @app_commands.default_permissions(administrator=True)
    async def create(self, interaction: discord.Interaction, name: str, public_log_channel: Optional[discord.TextChannel] = None, admin_log_channel: Optional[discord.TextChannel] = None):
        await interaction.response.defer(ephemeral=True)
        if "-" in name:
            await send_error(interaction, "名前にハイフン「-」を入れることはできません。")
            return
        
        new_uuid = str(uuid.uuid4())
        await MachineController.create_data(new_uuid, name, interaction.user.id, 0, "")
        pub_id = public_log_channel.id if public_log_channel else 0
        adm_id = admin_log_channel.id if admin_log_channel else 0
        await MachineLogSettings.set_log_channels(new_uuid, interaction.guild_id, pub_id, adm_id)

        embed = discord.Embed(title="✅ 成功", description=f"{cb}yaml\n自販機を作成しました。\n{cb}", color=discord.Color.green())
        embed.add_field(name="名前", value=f"{cb}yaml\n{name}\n{cb}", inline=False)
        embed.add_field(name="UUID", value=f"{cb}yaml\n{new_uuid}\n{cb}", inline=False)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="list", description="自分の自販機一覧を表示します")
    @app_commands.default_permissions(administrator=True)
    async def list_cmd(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        machines = await MachineController.get_machines_from_user_id(interaction.user.id)
        if not machines:
            await send_error(interaction, "所有している自販機がありません。")
            return
        
        embed = discord.Embed(title="📋 自販機一覧", color=discord.Color.blue())
        for m in machines:
            desc = m[4] if len(m) > 4 and m[4] else "説明なし"
            embed.add_field(name=f"🏪 {m[1]}", value=f"{cb}yaml\nUUID: {m[0]}\n説明: {desc}\n{cb}", inline=False)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="edit", description="自販機の設定を変更します")
    @app_commands.default_permissions(administrator=True)
    async def edit(self, interaction: discord.Interaction, name: Optional[str] = None, description: Optional[str] = None, public_log_channel: Optional[discord.TextChannel] = None, admin_log_channel: Optional[discord.TextChannel] = None):
        await interaction.response.defer(ephemeral=True)
        machines = await MachineController.get_machines_from_user_id(interaction.user.id)
        if not machines:
            await send_error(interaction, "所有している自販機がありません。")
            return
        
        pub_id = public_log_channel.id if public_log_channel else None
        adm_id = admin_log_channel.id if admin_log_channel else None

        embed = discord.Embed(title="⚙️ 自販機の編集", description=f"{cb}yaml\n編集する自販機を選択してください。\n{cb}", color=discord.Color.blue())
        await interaction.followup.send(embed=embed, view=MachineEditView(machines, name, description, pub_id, adm_id), ephemeral=True)

    @app_commands.command(name="delete", description="自販機を削除します")
    @app_commands.default_permissions(administrator=True)
    async def delete(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        machines = await MachineController.get_machines_from_user_id(interaction.user.id)
        if not machines:
            await send_error(interaction, "所有している自販機がありません。")
            return
        embed = discord.Embed(title="🗑️ 自販機の削除", description=f"{cb}yaml\n削除する自販機を選択してください。\n{cb}", color=discord.Color.red())
        await interaction.followup.send(embed=embed, view=MachineDeleteView(machines), ephemeral=True)

    @app_commands.command(name="summon", description="自販機を設置します")
    @app_commands.default_permissions(administrator=True)
    async def summon(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        machines = await MachineController.get_machines_from_user_id(interaction.user.id)
        if not machines:
            await send_error(interaction, "所有している自販機がありません。")
            return
        
        embed = discord.Embed(title="🏪 自販機の設置", description=f"{cb}yaml\nこのチャンネルに設置する自販機を選択してください。\n{cb}", color=discord.Color.purple())
        await interaction.followup.send(embed=embed, view=MachineSummonView(machines, self.bot), ephemeral=True)

class ProductGroup(app_commands.Group):
    def __init__(self, bot):
        super().__init__(name="product", description="商品管理コマンド")
        self.bot = bot

    @app_commands.command(name="create", description="商品を作成します")
    @app_commands.default_permissions(administrator=True)
    async def create(self, interaction: discord.Interaction, name: str, price: int, description: Optional[str] = "説明なし"):
        await interaction.response.defer(ephemeral=True)
        if "-" in name:
            await send_error(interaction, "名前にハイフン「-」を入れることはできません。")
            return
            
        machines = await MachineController.get_machines_from_user_id(interaction.user.id)
        if not machines:
            await send_error(interaction, "所有している自販機がありません。")
            return
            
        embed = discord.Embed(title="⚙️ 商品の作成", description=f"{cb}yaml\n商品を追加する自販機を選択してください。\n{cb}", color=discord.Color.blue())
        await interaction.followup.send(embed=embed, view=ProductCreateMachineView(machines, name, price, description), ephemeral=True)

    @app_commands.command(name="edit", description="商品の詳細（名前・価格・説明）をフォームで編集します")
    @app_commands.default_permissions(administrator=True)
    async def edit(self, interaction: discord.Interaction):
        """引数なしで実行すると、モーダルフローが開始されます"""
        await interaction.response.defer(ephemeral=True)
        machines = await MachineController.get_machines_from_user_id(interaction.user.id)
        if not machines:
            await send_error(interaction, "所有している自販機がありません。")
            return

        embed = discord.Embed(title="⚙️ 商品の編集", description=f"{cb}yaml\n編集したい商品が含まれる自販機を選択してください。\n{cb}", color=discord.Color.blue())
        await interaction.followup.send(embed=embed, view=MachineSelectForProductView(machines, "edit"), ephemeral=True)

    @app_commands.command(name="delete", description="商品を削除します")
    @app_commands.default_permissions(administrator=True)
    async def delete(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        machines = await MachineController.get_machines_from_user_id(interaction.user.id)
        if not machines:
            await send_error(interaction, "所有している自販機がありません。")
            return

        embed = discord.Embed(title="🗑️ 商品の削除", description=f"{cb}yaml\n削除する商品が含まれる自販機を選択してください。\n{cb}", color=discord.Color.red())
        await interaction.followup.send(embed=embed, view=MachineSelectForProductView(machines, "delete"), ephemeral=True)

    @app_commands.command(name="restock", description="在庫を追加します")
    @app_commands.default_permissions(administrator=True)
    async def restock(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        machines = await MachineController.get_machines_from_user_id(interaction.user.id)
        if not machines:
            await send_error(interaction, "所有している自販機がありません。")
            return

        embed = discord.Embed(title="📦 在庫の追加", description=f"{cb}yaml\n在庫を追加する商品が含まれる自販機を選択してください。\n{cb}", color=discord.Color.blue())
        await interaction.followup.send(embed=embed, view=MachineSelectForProductView(machines, "restock", bot=self.bot), ephemeral=True)

    @app_commands.command(name="takestock", description="在庫を取り出します")
    @app_commands.default_permissions(administrator=True)
    async def takestock(self, interaction: discord.Interaction, all_take: bool):
        await interaction.response.defer(ephemeral=True)
        machines = await MachineController.get_machines_from_user_id(interaction.user.id)
        if not machines:
            await send_error(interaction, "所有している自販機がありません。")
            return

        embed = discord.Embed(title="📦 在庫の取り出し", description=f"{cb}yaml\n在庫を取り出す商品が含まれる自販機を選択してください。\n{cb}", color=discord.Color.blue())
        await interaction.followup.send(embed=embed, view=MachineSelectForProductView(machines, "takestock", all_take=all_take), ephemeral=True)

    @app_commands.command(name="setstock", description="在庫追加通知を設定します")
    @app_commands.default_permissions(administrator=True)
    async def set_restock_notification(self, interaction: discord.Interaction, channel: discord.TextChannel, role: Optional[discord.Role] = None):
        await interaction.response.defer(ephemeral=True)
        role_id = role.id if role else 0
        await NotifyController.set_notify(interaction.guild_id, channel.id, role_id)
        
        if role:
            desc = f"{cb}yaml\n在庫追加通知を設定しました\nチャンネル: {channel.name}\nロール: {role.name}\n{cb}"
        else:
            desc = f"{cb}yaml\n在庫追加通知チャンネルを {channel.name} に設定しました。\n{cb}"
        embed = discord.Embed(title="✅ 成功", description=desc, color=discord.Color.green())
        await interaction.followup.send(embed=embed, ephemeral=True)

class CouponGroup(app_commands.Group):
    def __init__(self, bot):
        super().__init__(name="coupon", description="クーポン管理コマンド")
        self.bot = bot

    @app_commands.command(name="create", description="新しいクーポンコードを作成します")
    @app_commands.choices(target_type=[
        app_commands.Choice(name="全自販機対象", value="all"),
        app_commands.Choice(name="特定の自販機限定", value="machine"),
        app_commands.Choice(name="特定の商品限定", value="product")
    ])
    @app_commands.describe(
        code="クーポンの名前（例: SALE50）",
        discount_percent="割引率（1〜100）",
        usage_limit="使用可能回数（0で無制限）",
        target_type="クーポンの適用範囲",
        target_id="適用範囲が自販機/商品の場合はUUIDを入力"
    )
    @app_commands.default_permissions(administrator=True)
    async def create(self, interaction: discord.Interaction, code: str, discount_percent: int, usage_limit: int, target_type: str = "all", target_id: Optional[str] = None):
        await interaction.response.defer(ephemeral=True)
        if discount_percent < 1 or discount_percent > 100:
            await send_error(interaction, "割引率は1〜100の間で設定してください。")
            return
        
        if target_type != "all" and not target_id:
            await send_error(interaction, "特定の自販機や商品を対象にする場合は、対象のUUID(target_id)を指定してください。")
            return

        try:
            await CouponController.create_coupon(code, discount_percent, usage_limit, target_type, target_id)
            embed = discord.Embed(title="✅ クーポン作成", description=f"{cb}yaml\nクーポンを作成しました。\n{cb}", color=discord.Color.green())
            embed.add_field(name="コード", value=f"{cb}yaml\n{code}\n{cb}", inline=False)
            embed.add_field(name="割引率", value=f"{cb}yaml\n{discount_percent}%\n{cb}", inline=True)
            limit_str = "無制限" if usage_limit == 0 else f"{usage_limit}回"
            embed.add_field(name="使用上限", value=f"{cb}yaml\n{limit_str}\n{cb}", inline=True)
            embed.add_field(name="適用範囲", value=f"{cb}yaml\nタイプ: {target_type}\n対象ID: {target_id or 'なし'}\n{cb}", inline=False)
            await interaction.edit_original_response(embed=embed)
        except Exception as e:
            await send_error(interaction, f"クーポンの作成に失敗しました。コードが重複している可能性があります。\n詳細: {e}")

    @app_commands.command(name="list", description="作成したクーポン一覧を表示します")
    @app_commands.default_permissions(administrator=True)
    async def list_cmd(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        coupons = await CouponController.get_all_coupons()
        if not coupons:
            await send_error(interaction, "現在登録されているクーポンはありません。")
            return
        
        embed = discord.Embed(title="🎟️ クーポン一覧", color=discord.Color.blue())
        for c in coupons:
            limit_str = "無制限" if c[2] == 0 else f"{c[3]}/{c[2]}回"
            embed.add_field(name=f"🎫 {c[0]}", value=f"{cb}yaml\n割引: {c[1]}%\n使用状況: {limit_str}\n適用範囲: {c[4]}\n対象ID: {c[5]}\n{cb}", inline=False)
        await interaction.edit_original_response(embed=embed)

    @app_commands.command(name="delete", description="指定したクーポンを削除します")
    @app_commands.default_permissions(administrator=True)
    async def delete(self, interaction: discord.Interaction, code: str):
        await interaction.response.defer(ephemeral=True)
        coupon = await CouponController.get_coupon(code)
        if not coupon:
            await send_error(interaction, "指定されたクーポンコードは見つかりません。")
            return
            
        await CouponController.delete_coupon(code)
        embed = discord.Embed(title="🗑️ 削除完了", description=f"{cb}yaml\nクーポン「{code}」を削除しました。\n{cb}", color=discord.Color.red())
        await interaction.edit_original_response(embed=embed)

    @app_commands.command(name="edit", description="指定したクーポンの設定を変更します")
    @app_commands.default_permissions(administrator=True)
    async def edit(self, interaction: discord.Interaction, code: str, discount_percent: Optional[int] = None, usage_limit: Optional[int] = None, target_type: Optional[str] = None, target_id: Optional[str] = None):
        await interaction.response.defer(ephemeral=True)
        coupon = await CouponController.get_coupon(code)
        if not coupon:
            await send_error(interaction, "指定されたクーポンコードは見つかりません。")
            return
            
        if target_type and target_type != "all" and not target_id and coupon[5] is None:
            await send_error(interaction, "対象をall以外にする場合はtarget_idが必要です。")
            return

        await CouponController.update_coupon(code, discount_percent, usage_limit, target_type, target_id)
        embed = discord.Embed(title="✅ 編集完了", description=f"{cb}yaml\nクーポン「{code}」の設定を更新しました。\n{cb}", color=discord.Color.green())
        await interaction.edit_original_response(embed=embed)


class VendingCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.paypay_group = PayPayGroup(bot)
        self.machine_group = MachineGroup(bot)
        self.product_group = ProductGroup(bot)
        self.coupon_group = CouponGroup(bot)
        
        self.bot.tree.add_command(self.paypay_group)
        self.bot.tree.add_command(self.machine_group)
        self.bot.tree.add_command(self.product_group)
        self.bot.tree.add_command(self.coupon_group)

    async def cog_load(self):
        await PayPayController.initialize()
        await MachineController.initialize()
        await ProductController.initialize()
        await StockController.initialize()
        await CouponController.initialize()
        await NotifyController.initialize()
        await MachineLogSettings.initialize()
        
        async with aiosqlite.connect("./data/product.db") as db:
            try:
                await db.execute("ALTER TABLE product ADD COLUMN sales INTEGER DEFAULT 0")
                await db.commit()
            except:
                pass
                
        self.bot.add_view(InfoButton(self.bot))

    async def cog_unload(self):
        self.bot.tree.remove_command("paypay")
        self.bot.tree.remove_command("machine")
        self.bot.tree.remove_command("product")
        self.bot.tree.remove_command("coupon")

    @app_commands.command(name="実績チャンネル一覧", description="各サーバーで設定した自販機や通知の実績チャンネルを一覧で確認します")
    @app_commands.default_permissions(administrator=True)
    async def log_list(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        guild_id = interaction.guild_id
        
        # 1. 在庫通知の設定を取得
        notify_data = await NotifyController.get_notify(guild_id)
        notify_val = f"{cb}yaml\n未設定\n{cb}"
        if notify_data and notify_data[0]:
            notify_val = f"<#{notify_data[0]}>"
            if notify_data[1]:
                notify_val += f" (通知ロール: <@&{notify_data[1]}>)"

        # 2. 自販機ごとの実績チャンネルを取得
        async with aiosqlite.connect("./data/vending_logs.db") as db:
            cursor = await db.execute("SELECT machine_uuid, public_channel_id, admin_channel_id FROM machine_logs WHERE guild_id=?", (guild_id,))
            logs = await cursor.fetchall()

        machine_texts = []
        for log in logs:
            m_uuid, pub_id, adm_id = log
            _uuid, name, _, _, _ = await MachineController.get_machine_from_machine_uuid(m_uuid)
            if not name:
                continue
            
            pub_text = f"<#{pub_id}>" if pub_id else "未設定"
            adm_text = f"<#{adm_id}>" if adm_id else "未設定"
            machine_texts.append(f"🏪 **{name}**\n┣ 公開用実績: {pub_text}\n┗ 管理者用ログ: {adm_text}")

        embed = discord.Embed(title="📊 実績・通知チャンネル一覧", color=discord.Color.blue())
        embed.add_field(name="📦 在庫追加通知チャンネル", value=notify_val, inline=False)
        
        if not machine_texts:
            embed.add_field(name="🏪 自販機別 実績チャンネル", value=f"{cb}yaml\n設定されている自販機実績はありません。\n{cb}", inline=False)
        else:
            machine_str = "\n\n".join(machine_texts)
            if len(machine_str) > 1024:
                machine_str = machine_str[:1000] + "\n...(以下省略)"
            embed.add_field(name="🏪 自販機別 実績チャンネル", value=machine_str, inline=False)

        await interaction.edit_original_response(embed=embed)

async def setup(bot):
    await bot.add_cog(VendingCog(bot))