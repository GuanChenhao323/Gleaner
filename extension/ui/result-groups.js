const TITLES={courses:'课程概览',assignments:'作业与活动',timeline:'Timeline 活动',contacts:'联系信息',sections:'页面区块',other:'匹配内容'};
const TYPES={course_entry:'courses',assignment:'assignments',timeline_event:'timeline',contact_info:'contacts',page_section:'sections'};

/** Presentation policy only. Grouping cannot select, discard or authorize saving. */
export class ResultGroups {
  previewGuidance(candidates) {
    if(candidates.every(c=>c.record_type==='contact_info'))return {message:'联系信息仅供查阅，本次不会创建事项。可修改字段条件重新读取。',button:'联系信息仅预览'};
    if(candidates.every(c=>c.record_type==='timeline_event'))return {message:'时间线当前只有活动摘要。请使用“打开原文”进入活动详情，再按条件抓取并保存。',button:'仅预览，请打开活动详情'};
    return {message:'本组包含入口或不完整内容，不能整批保存。可缩小条件，例如输入“课程名的作业”，或打开对应详情后重试。',button:'仅预览，请打开详情或缩小条件'};
  }
  arrange(candidates) {
    const groups=new Map();
    for(const candidate of candidates) {
      const id=candidate.presentation?.group || TYPES[candidate.record_type] || 'other';
      if(!groups.has(id)) groups.set(id,[]);
      groups.get(id).push(candidate);
    }
    return Object.entries(TITLES).filter(([id])=>groups.has(id)).map(([id,title])=>({id,title,candidates:groups.get(id)}));
  }
}
