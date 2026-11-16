/** Login requirements are separate from content adapters and from data sharing. */
export class LoginRequirementPolicy {
  requiresLogin(url, account) {
    const host=new URL(url).hostname;
    return ['mail.google.com','wx.mail.qq.com'].includes(host) || account?.state==='known';
  }
}
