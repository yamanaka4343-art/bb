import discord
from discord import app_commands
from discord.ext import commands
import asyncio
import os

from utils.controller import PayPayController

cb = '`' * 3

class PayCreateCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="paypay_createlink", description="指定した金額のPayPay送金リンクを作成します")
    @app_commands.describe(amount="送金する金額 (1〜100000)")
    async def createlink(self, interaction: discord.Interaction, amount: int):
        # 3秒ルール対策（リンクは全員が見えるようにするため ephemeral=False）
        await interaction.response.defer(ephemeral=False)

        # 1. 金額のバリデーション
        if amount < 1 or amount > 100000:
            err = discord.Embed(title="❌ エラー", description=f"{cb}yaml\n金額は1〜100000の範囲で指定してください。\n{cb}", color=discord.Color.red())
            await interaction.followup.send(embed=err)
            return

        loading_embed = discord.Embed(title="🔄 処理中", description=f"{cb}yaml\nアカウント情報を確認し、送金リンクを生成しています...\n{cb}", color=discord.Color.yellow())
        await interaction.edit_original_response(embed=loading_embed)

        try:
            # 2. PayPayアカウントの取得
            paypay = await PayPayController.get_client(interaction.user.id)
            if not paypay:
                err = discord.Embed(
                    title="❌ エラー", 
                    description=f"{cb}yaml\nPayPayアカウントが登録されていません。\n/paypay login で連携してから再度お試しください。\n{cb}", 
                    color=discord.Color.red()
                )
                await interaction.edit_original_response(embed=err)
                return

            # 3. プロフィール情報(電話番号)の取得とマスキング処理
            phone_str = "取得不可"
            try:
                profile = await asyncio.to_thread(paypay.get_profile)
                
                # AttributeDict対応
                if hasattr(profile, "payload"):
                    payload_prof = profile.payload
                    phone_val = getattr(payload_prof, "phone", getattr(payload_prof, "maskedPhone", "取得不可"))
                else:
                    payload_prof = profile.get("payload", {})
                    phone_val = payload_prof.get("phone", payload_prof.get("maskedPhone", "取得不可"))
                    
                raw_phone = str(phone_val).replace("-", "")
                if raw_phone and raw_phone != "取得不可":
                    phone_str = raw_phone
            except:
                pass

            # 最初と最後の4桁以外を * で隠す処理
            if phone_str != "取得不可" and len(phone_str) >= 8:
                masked_phone = f"{phone_str[:4]}{'*' * (len(phone_str) - 8)}{phone_str[-4:]}"
            else:
                masked_phone = phone_str

            # 4. リンクの作成 (参考コードに合わせて execute_link を優先使用)
            try:
                if hasattr(paypay, "execute_link"):
                    link_res = await asyncio.to_thread(paypay.execute_link, amount)
                elif hasattr(paypay, "create_link"):
                    link_res = await asyncio.to_thread(paypay.create_link, amount)
                else:
                    raise Exception("使用しているPayPayPyライブラリにリンク作成機能が見つかりません。")
            except Exception as api_err:
                raise Exception(f"API呼び出し失敗: {api_err}")

            # 5. どんな階層でも確実にデータを引っこ抜くための探索関数（AttributeDictの解体）
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

            res_dict = to_dict(link_res)

            def find_key(d, target_key):
                if isinstance(d, dict):
                    for k, v in d.items():
                        if k.lower() == target_key.lower():
                            return v
                        res = find_key(v, target_key)
                        if res is not None:
                            return res
                elif isinstance(d, list):
                    for item in d:
                        res = find_key(item, target_key)
                        if res is not None:
                            return res
                return None

            # 6. 値の抽出実行 (大文字小文字を無視して全階層を探す)
            url = find_key(res_dict, "url") or find_key(res_dict, "linkurl")
            verification_code = find_key(res_dict, "verificationcode")
            order_id = find_key(res_dict, "orderid")

            # URLが見つからなかった場合、文字列から直接PayPayリンクを探し出す安全策
            if not url:
                def find_url(d):
                    if isinstance(d, dict):
                        for v in d.values():
                            res = find_url(v)
                            if res: return res
                    elif isinstance(d, list):
                        for v in d:
                            res = find_url(v)
                            if res: return res
                    elif isinstance(d, str) and "pay.paypay.ne.jp/" in d:
                        return d
                    return None
                url = find_url(res_dict)

            # URLとCodeの相互補完
            if url and not verification_code:
                verification_code = str(url).split("/")[-1]
            elif verification_code and not url:
                url = f"https://pay.paypay.ne.jp/{verification_code}"

            if not verification_code or not url:
                print(f"【デバッグ】データ抽出失敗。取得したデータ: {res_dict}")
                raise Exception("リンクのURLまたは認証コードの取得に失敗しました。")

            # 7. 結果のEmbed作成
            embed = discord.Embed(title="🔗 PayPay送金リンク", color=discord.Color.red())
            embed.add_field(name="Label (アカウント)", value=f"{cb}yaml\n{masked_phone}\n{cb}", inline=False)
            embed.add_field(name="金額", value=f"{cb}yaml\n{amount}円\n{cb}", inline=False)
            embed.add_field(name="リンク", value=f"{url}", inline=False)
            
            await interaction.edit_original_response(embed=embed)

        except Exception as e:
            err = discord.Embed(title="❌ エラー", description=f"{cb}yaml\nリンクの作成処理中にエラーが発生しました。\n{e}\n{cb}", color=discord.Color.red())
            await interaction.edit_original_response(embed=err)

async def setup(bot):
    await bot.add_cog(PayCreateCog(bot))