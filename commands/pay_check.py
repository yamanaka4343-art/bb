import discord
from discord import app_commands
from discord.ext import commands
import asyncio

from utils.controller import PayPayController

cb = '`' * 3

class PayCheckCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="残高確認", description="連携しているPayPayの残高（マネー/マネーライト）を確認します")
    async def check_balance(self, interaction: discord.Interaction):
        # 3秒ルール対策: 先にdeferで「考え中」状態にし、他人には見えない設定(ephemeral=True)にする
        await interaction.response.defer(ephemeral=True)

        loading_embed = discord.Embed(
            title="🔄 処理中", 
            description=f"{cb}yaml\nPayPayの残高情報を取得しています...\n{cb}", 
            color=discord.Color.yellow()
        )
        await interaction.followup.send(embed=loading_embed)

        try:
            # 1. ユーザーのPayPayクライアントを取得
            paypay = await PayPayController.get_client(interaction.user.id)
            if not paypay:
                err = discord.Embed(
                    title="❌ エラー", 
                    description=f"{cb}yaml\nPayPayアカウントが登録されていません。\n/paypay login で連携してから再度お試しください。\n{cb}", 
                    color=discord.Color.red()
                )
                await interaction.edit_original_response(embed=err)
                return

            # 2. 残高情報の取得 (API呼び出し)
            try:
                balance_res = await asyncio.to_thread(paypay.get_balance)
            except Exception as api_err:
                raise Exception(f"API呼び出し失敗: {api_err}")

            # 3. ペイロード部分のみを安全に抽出
            payload = None
            if hasattr(balance_res, "payload"):
                payload = balance_res.payload
            elif hasattr(balance_res, "obj") and isinstance(balance_res.obj, dict):
                payload = balance_res.obj.get("payload")
            elif isinstance(balance_res, dict):
                payload = balance_res.get("payload")

            if payload is None:
                payload = balance_res # フォールバック

            # 扱いやすいように辞書型に完全変換する
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

            res_dict = to_dict(payload)

            # 4. 指定したキーから入れ子になった balance を安全に取得する関数 (0円問題対策済み)
            def find_balance_by_keys(data, *target_keys):
                def _search(d, target_key):
                    if isinstance(d, dict):
                        for k, v in d.items():
                            if k.lower() == target_key.lower():
                                if isinstance(v, dict):
                                    # 辞書の中に balance があればそれを返す
                                    for vk, vv in v.items():
                                        if vk.lower() == "balance":
                                            try: return int(vv)
                                            except: pass
                                # 直に数値が入っている場合
                                if v is not None:
                                    try: return int(v)
                                    except: pass
                                else:
                                    return 0 # null(None)として入っている場合は0扱い
                            res = _search(v, target_key)
                            if res is not None:
                                return res
                    elif isinstance(d, list):
                        for item in d:
                            res = _search(item, target_key)
                            if res is not None:
                                return res
                    return None

                for key in target_keys:
                    val = _search(data, key)
                    if val is not None:
                        return val # 0円でも None ではないので確実にリターンする
                return 0

            # 5. 残高データの抽出 (最新のPayPay JSONフォーマットに対応)
            # マネー: payoutableBalanceInfo(出金可能), emoneyBalanceInfo 等
            money_balance = find_balance_by_keys(res_dict, "payoutableBalanceInfo", "emoneyBalanceInfo", "insuredEmoneyBalanceInfo", "moneyBalanceInfo", "moneyBalance")
            # マネーライト: prepaidBalanceInfo(プリペイド), moneyLightBalanceInfo 等
            money_light_balance = find_balance_by_keys(res_dict, "prepaidBalanceInfo", "moneyLightBalanceInfo", "moneyLightBalance")
            # ポイント: totalPayPayPointsInfo, cashBackBalanceInfo 等
            point_balance = find_balance_by_keys(res_dict, "totalPayPayPointsInfo", "cashBackBalanceInfo", "bonusBalanceInfo", "bonusBalance", "pointBalanceInfo", "pointBalance")
            
            # APIが返してくる総合計
            total_api = find_balance_by_keys(res_dict, "allTotalBalanceInfo", "totalBalanceInfo", "totalBalance")

            # 計算上の合計
            total_calc = money_balance + money_light_balance + point_balance
            
            # どちらか大きい方を総残高として扱う
            total_balance = max(total_calc, total_api)

            # 6. 万が一すべて0円だった場合の原因究明用メッセージ
            debug_msg = ""
            if total_balance == 0:
                raw_data = str(res_dict)[:250]
                debug_msg = f"{cb}yaml\n※残高が0円になっています。\n別のアカウントで連携しているか、本当に0円の可能性があります。\n【システムデバッグ】\n{raw_data}...\n{cb}"

            # 7. 結果のEmbedを作成して表示
            embed = discord.Embed(title="💰 PayPay残高照会", color=discord.Color.from_rgb(255, 0, 51)) # PayPayの赤色
            embed.add_field(name="総残高", value=f"{cb}yaml\n{total_balance:,} 円\n{cb}", inline=False)
            embed.add_field(name="PayPayマネー", value=f"{cb}yaml\n{money_balance:,} 円\n{cb}", inline=True)
            embed.add_field(name="PayPayマネーライト", value=f"{cb}yaml\n{money_light_balance:,} 円\n{cb}", inline=True)
            embed.add_field(name="ポイント・ボーナス", value=f"{cb}yaml\n{point_balance:,} pt\n{cb}", inline=True)
            
            if debug_msg:
                embed.add_field(name="⚠️ お知らせ", value=debug_msg, inline=False)
            
            await interaction.edit_original_response(embed=embed)

        except Exception as e:
            err = discord.Embed(title="❌ エラー", description=f"{cb}yaml\n残高照会中にエラーが発生しました。\n{e}\n{cb}", color=discord.Color.red())
            await interaction.edit_original_response(embed=err)

async def setup(bot):
    await bot.add_cog(PayCheckCog(bot))
