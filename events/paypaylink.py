import discord
from discord.ext import commands
import re
import asyncio
import aiosqlite
from datetime import datetime, timezone, timedelta

from utils.controller import PayPayController

cb = '`' * 3

# PayPayのISO8601形式の日付を日本時間に変換する関数
def parse_paypay_date(date_str):
    if not date_str:
        return "不明"
    try:
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        dt_jst = dt.astimezone(timezone(timedelta(hours=9)))
        return dt_jst.strftime("%Y年%m月%d日 %H時%M分%S秒")
    except:
        return date_str

# どんな階層でも確実にデータを引っこ抜くための探索関数（AttributeDictの解体）
def to_dict(obj):
    if hasattr(obj, "fields") and callable(getattr(obj, "fields")):
        return {k: to_dict(v) for k, v in obj.fields().items()}
    elif hasattr(obj, "obj") and isinstance(getattr(obj, "obj"), dict):
        return {k: to_dict(v) for k, v in obj.obj.items()}
    elif isinstance(obj, dict):
        return {k: to_dict(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [to_dict(v) for v in obj]
    return obj

def find_key(data, target_key):
    if isinstance(data, dict):
        for k, v in data.items():
            if k.lower() == target_key.lower():
                return v
            res = find_key(v, target_key)
            if res is not None:
                return res
    elif isinstance(data, list):
        for item in data:
            res = find_key(item, target_key)
            if res is not None:
                return res
    return None

class PayPayAccountSelect(discord.ui.Select):
    def __init__(self, verification_code, original_message):
        # 現在のデータベース構造（1人1アカウント）に合わせ、登録済みのアカウントを表示します。
        options = [
            discord.SelectOption(
                label="登録済みアカウント", 
                description="現在連携されているPayPayアカウントを使用します", 
                emoji="📱", 
                value="default"
            )
        ]
        super().__init__(placeholder="受け取るアカウントを選択してください", options=options)
        self.verification_code = verification_code
        self.original_message = original_message

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        # 押した本人のアカウントを取得
        paypay = await PayPayController.get_client(interaction.user.id)
        if not paypay:
            err = discord.Embed(
                title="❌ エラー", 
                description=f"{cb}yaml\nPayPayアカウントが登録されていません。\n/paypay login で連携してから再度お試しください。\n{cb}", 
                color=discord.Color.red()
            )
            await interaction.followup.send(embed=err, ephemeral=True)
            return
            
        try:
            # 受け取り処理の実行
            api_res = await asyncio.to_thread(paypay.accept_link, self.verification_code, None)
            
            # 結果を安全に辞書化して抽出
            res_dict = to_dict(api_res)
            result_code = find_key(res_dict, "resultCode")
            
            if result_code == "S0000":
                # 成功: 元のメッセージのボタンを灰色に変更
                view = discord.ui.View(timeout=None)
                btn = discord.ui.Button(label="受け取り済み", style=discord.ButtonStyle.secondary, disabled=True)
                view.add_item(btn)
                await self.original_message.edit(view=view)
                
                succ = discord.Embed(
                    title="✅ 成功", 
                    description=f"{cb}yaml\nPayPay残高の受け取りが完了しました！\n{cb}", 
                    color=discord.Color.green()
                )
                await interaction.followup.send(embed=succ, ephemeral=True)
            else:
                err_msg = find_key(res_dict, "resultMessage") or "詳細不明"
                err = discord.Embed(
                    title="❌ 失敗", 
                    description=f"{cb}yaml\n受け取りに失敗しました。\n・リンクが使用済み\n・パスコードが必要\n・自身が作成したリンク\nなどの可能性があります。\n\n詳細: {err_msg}\n{cb}", 
                    color=discord.Color.red()
                )
                await interaction.followup.send(embed=err, ephemeral=True)
                
        except Exception as e:
            err_str = str(e)
            # PayPayPy 特有のハーフシートエラーの検知
            if "half sheet" in err_str or "S9999" in err_str:
                desc = f"{cb}yaml\nこのリンクは受け取れませんでした。\n・パスコードが設定されている\n・自身が作成したリンクである\n・すでに辞退/期限切れになっている\nなどの原因が考えられます。\n{cb}"
            else:
                desc = f"{cb}yaml\n処理中にシステムエラーが発生しました:\n{err_str}\n{cb}"
                
            err = discord.Embed(
                title="❌ 受け取り失敗", 
                description=desc, 
                color=discord.Color.red()
            )
            await interaction.followup.send(embed=err, ephemeral=True)

class PayPayLinkView(discord.ui.View):
    def __init__(self):
        # 永続化するために timeout=None に設定
        super().__init__(timeout=None)

    @discord.ui.button(label="受け取る", style=discord.ButtonStyle.danger, custom_id="paypay_auto_receive_btn")
    async def receive_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.message.embeds:
            await interaction.response.send_message(embed=discord.Embed(title="❌ エラー", description=f"{cb}yaml\n情報の取得に失敗しました。\n{cb}", color=discord.Color.red()), ephemeral=True)
            return
            
        embed = interaction.message.embeds[0]
        if not embed.url:
            await interaction.response.send_message(embed=discord.Embed(title="❌ エラー", description=f"{cb}yaml\nリンク情報の取得に失敗しました。\n{cb}", color=discord.Color.red()), ephemeral=True)
            return
            
        # URLから検証コードを逆算
        verification_code = embed.url.split("/")[-1]
        
        view = discord.ui.View(timeout=180)
        view.add_item(PayPayAccountSelect(verification_code, interaction.message))
        
        select_embed = discord.Embed(
            title="📱 アカウント選択", 
            description=f"{cb}yaml\n残高を受け取るPayPayアカウントを選択してください。\n{cb}", 
            color=discord.Color.blue()
        )
        await interaction.response.send_message(embed=select_embed, view=view, ephemeral=True)

class PayPayLinkEvents(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.link_pattern = re.compile(r"https://pay\.paypay\.ne\.jp/([a-zA-Z0-9]+)")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # BOT自身のメッセージは無視
        if message.author.bot:
            return

        match = self.link_pattern.search(message.content)
        if match:
            verification_code = match.group(1)
            
            # DBから適当なアカウントを1つ取得してリンク情報を取得する
            async with aiosqlite.connect("./data/paypay.db") as db:
                cursor = await db.execute("SELECT user_id FROM paypay LIMIT 1")
                row = await cursor.fetchone()
                
            if not row:
                return # 誰もPayPayを登録していない場合は取得不可として無視
                
            paypay = await PayPayController.get_client(row[0])
            if not paypay:
                return
                
            try:
                check_result = await asyncio.to_thread(paypay.get_link, verification_code)
            except Exception as e:
                print(f"PayPayリンク情報取得エラー: {e}")
                return
                
            # APIの戻り値を辞書化して安全にデータを抽出
            res_dict = to_dict(check_result)
            
            # ステータスの確認
            order_status = find_key(res_dict, "orderStatus")
            if order_status != "PENDING":
                # PENDING以外（使用済み、キャンセル等）ならスルー
                return
                
            # 各種データの抽出（最新のJSONフォーマットに基づき優先順位を設定）
            sender_name = find_key(res_dict, "userDisplayName") or find_key(res_dict, "displayName") or "不明"
            
            # 金額情報の抽出
            amount = find_key(res_dict, "amount") or 0
            # マネー: senderEmoneyAmount 優先
            charge_amount = find_key(res_dict, "senderEmoneyAmount") or find_key(res_dict, "chargeAmount") or 0
            # マネーライト: senderPrepaidAmount 優先
            money_light_amount = find_key(res_dict, "senderPrepaidAmount") or find_key(res_dict, "moneyLightAmount") or 0
            
            order_id = find_key(res_dict, "orderId") or "不明"
            
            # 日付キーの調整
            created_at_raw = find_key(res_dict, "createdAt")
            expire_at_raw = find_key(res_dict, "expiredAt") or find_key(res_dict, "expireAt")
            
            created_at = parse_paypay_date(created_at_raw)
            expire_at = parse_paypay_date(expire_at_raw)
            
            embed = discord.Embed(
                title="PayPay Auto Receive", 
                description=f"**{sender_name}**さんから受け取る", 
                color=discord.Color.from_rgb(255, 0, 51),
                url=f"https://pay.paypay.ne.jp/{verification_code}"
            )
            embed.add_field(name="送信者", value=f"{cb}yaml\n{sender_name}\n{cb}", inline=False)
            embed.add_field(name="合計金額", value=f"{cb}yaml\n{amount}円\n{cb}", inline=False)
            embed.add_field(name="マネー", value=f"{cb}yaml\n{charge_amount}円\n{cb}", inline=False)
            embed.add_field(name="マネーライト", value=f"{cb}yaml\n{money_light_amount}円\n{cb}", inline=False)
            embed.add_field(name="取引番号", value=f"{cb}yaml\n{order_id}\n{cb}", inline=False)
            embed.add_field(name="作成日時", value=f"{cb}yaml\n{created_at}\n{cb}", inline=False)
            embed.add_field(name="有効期限", value=f"{cb}yaml\n{expire_at}\n{cb}", inline=False)
            
            embed.set_footer(text="Created by 𝖇𝖊𝖆 Security System")
            
            await message.reply(embed=embed, view=PayPayLinkView(), mention_author=False)

async def setup(bot):
    # ボタンを再起動後も永続的に機能させる
    bot.add_view(PayPayLinkView())
    await bot.add_cog(PayPayLinkEvents(bot))
