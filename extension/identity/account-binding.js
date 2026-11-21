const KEY=/^[a-f0-9]{64}$/;
export function accountIdentity(value) {
  if(!value || Object.keys(value).sort().join(',')!=='account_key,display,probe,version' || value.version!==1 || value.probe!=='account-control-email-v1' || !KEY.test(value.account_key) || typeof value.display!=='string' || value.display.length>100 || !/^[^@\s]+\*\*\*@[^@\s]+$/.test(value.display))throw Error('invalid_account_proof');
  return {version:1,probe:value.probe,account_key:value.account_key,display:value.display};
}
/** The worker owns account hashing. Labels and input keywords never enter this proof. */
export class AccountBindingService {
  constructor(reader,accountKey) {Object.assign(this,{reader,accountKey});}
  async verify(task) {
    const meta=await this.reader.metadata(task.tabId);
    if(meta.url!==task.url)throw Error('route_mismatch');
    if(meta.login)throw Error('need_login');
    if(meta.source!=='generic' || meta.account?.state!=='known' || meta.account.probe!=='account-control-email-v1')throw Error('account_unknown');
    const key=await this.accountKey('generic',meta.account.native);
    if(!task.observed_account_key)throw Error('account_reextract_required');
    if(key!==task.observed_account_key)throw Error('account_mismatch');
    const [local,domain]=meta.account.native.split('@');
    return accountIdentity({version:1,probe:meta.account.probe,account_key:key,display:local.slice(0,1)+'***@'+domain});
  }
}
