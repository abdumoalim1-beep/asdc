# asdc — محرك أتمتة المستندات المتكررة

تطبيق يستخدم الـ system prompt في `prompts/system_prompt.txt` كطبقة وسيطة (NLU):
يحوّل رسالة المستخدم العربية إلى JSON منظم، ثم يتحقق منه برمجيًا قبل تنفيذه
على بيانات وقوالب حقيقية — بدون تنفيذ أي شيء لم يُتحقق منه، وبدون اختراع بيانات.

## البنية

```
prompts/system_prompt.txt      نص الـ system prompt كما هو (لا يُعدَّل يدويًا داخل الكود)
data/workspace_entities.json   قاعدة بيانات وهمية (عملاء / منتجات / مؤثرين)
data/available_templates.json  قوالب المستندات المتاحة
src/asdc/
  schema.py       نموذج pydantic صارم لشكل رد النموذج (يطابق العقد في الـ prompt)
  llm_client.py   يبني الطلب (user_message + workspace_entities + available_templates
                  + conversation_history) ويستدعي النموذج، ويرفض أي رد لا يطابق العقد
  store.py        مخزن الكيانات (قراءة/تحديث/إضافة/بحث)
  templates.py    تعبئة القوالب وتوليد المستندات (نسخة جديدة دومًا للمستندات الموقّعة)
  validator.py    يتحقق أن matched_entity_id و template_requested موجودين فعليًا
                  قبل أي تنفيذ
  executor.py     ينفذ الإجراء المُتحقق منه فقط (add_entity / update_field /
                  generate_document / query)
  cli.py          REPL تفاعلي يربط كل الطبقات
tests/            اختبارات لكل طبقة + اختبار end-to-end بدون الحاجة لمفتاح API حقيقي
```

## التشغيل

```bash
pip install -r requirements.txt
export OPENAI_API_KEY=sk-...
export ASDC_MODEL=gpt-5-mini   # اختياري، هذا الافتراضي
python -m asdc.cli
```

مثال:

```
> غيّر سعر باقة الفعاليات لـ 500 ريال
تم تحديث سعر باقة الفعاليات إلى 500 ريال. هل تبي أحدّث المستندات المرتبطة بها الآن؟
  detail: {'entity_id': 'prod_014', 'fields': {'السعر': '500', ...}}
```

## الاختبارات

```bash
pip install -r requirements-dev.txt
pytest
```

الاختبارات لا تستدعي API خارجي — تستخدم دالة `completion_fn` وهمية تُحاكي رد
النموذج، لتغطية طبقات `schema` / `validator` / `executor` / `llm_client` وربطها
ببعض في اختبار end-to-end.

## القواعد المطبَّقة فعليًا في الكود (وليس فقط في نص الـ prompt)

- **لا اختراع بيانات:** `templates.render_template` يترك أي placeholder ناقص
  كما هو ويُرجع اسمه في `missing_fields`؛ `executor.execute` يرفض توليد المستند
  عندها بدلًا من تعبئته بقيمة افتراضية.
- **matched_entity_id غير موجود = رفض تنفيذ:** `validator.validate` يتحقق أن
  المعرّف موجود فعليًا في `EntityStore` قبل أي تحديث أو توليد مستند.
- **لا تحديث جماعي ضمني:** بما أن عقد الـ JSON الحالي لا يحمل حقل "طبّق على
  الكل"، فإن `update_field` بدون `matched_entity_id` محدد يُرفض صراحة بدلًا من
  تخمين الكيانات المستهدفة.
- **القوالب فقط من `available_templates`:** `validator.validate` يرفض أي
  `template_requested` غير موجود في `TemplateStore`، وأيضًا يرفض تطبيق قالب
  على نوع كيان مختلف عن `applies_to` الخاص به.
- **عدم تعديل المستندات الموقّعة:** `templates.generate_document` يفحص
  `entity.has_locked_document()`، وإن وُجد مستند بحالة "موقّع" أو "مُرسل" فإنه
  يُضيف نسخة جديدة (`entity.documents.append(...)`) ولا يلمس القديم إطلاقًا.
- **لا تنفيذ بدون تحقق:** `executor.execute` يستدعي `validator.validate` داخليًا
  ويرفع `ExecutionRefused` عند أي فشل، بدل تنفيذ `fields_to_update` مباشرة على
  قاعدة البيانات كما يحذّر نص الـ prompt.

## ملاحظات

- الـ system prompt نفسه في `prompts/system_prompt.txt` لم يُعدَّل عن النص
  الأصلي المُعطى — الكود هو ما يضيف طبقة التحقق والتنفيذ حوله.
- `llm_client.openai_completion_fn` هو التكامل الافتراضي مع OpenAI (كما في
  ملاحظات الاستخدام الأصلية التي تقترح تجربة GPT-5 mini/nano أولًا)، لكنه
  معزول خلف نوع الدالة `CompletionFn` — يمكن استبداله بأي مزوّد آخر بدون تعديل
  باقي الطبقات.
