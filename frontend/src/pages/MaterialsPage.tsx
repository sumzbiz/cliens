/**
 * Step 4 — the concrete mix and the walling.
 *
 * Presented as a summary you read, with each value opening a focused popup to
 * change it. A form of six controls read in one glance is harder to check than four
 * plain statements; and a popup gives each number room for the units, the range and
 * the reason it matters, which a cramped inline field cannot.
 */
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { PageShell } from '@/components/Shell';
import { VoiceExplainer } from '@/components/VoiceExplainer';
import { buildNarration, TA } from '@/lib/narration.ta';
import { useVoice } from '@/state/voice-context';
import { Button, CONTROL, ChoiceCard, Field, Panel, Popup } from '@/components/ui';
import { useSession } from '@/state/session-context';
import { CEMENT_TYPES, CONCRETE_GRADES, WALLING_MATERIALS } from '@/types/api';
import { useLanguage } from '@/state/language-context';

/** Which popup is open, if any. */
type Editor = 'grade' | 'cement' | 'ratio' | 'walling' | null;

export default function MaterialsPage() {
  const { spec, update, updateConcrete } = useSession();
  const navigate = useNavigate();
  const [editor, setEditor] = useState<Editor>(null);
  const voice = useVoice();
  const { t, language } = useLanguage();

  const close = () => {
    setEditor(null);
  };

  const wallingLabel =
    WALLING_MATERIALS.find((material) => material.value === spec.wallingMaterialId)?.label ??
    spec.wallingMaterialId;
  const cementLabel =
    CEMENT_TYPES.find((type) => type.value === spec.concrete.cement_type)?.label ??
    spec.concrete.cement_type;

  return (
    <PageShell
      eyebrow="Step 4 of 5"
      title="What are you building with?"
      lead="Tap any line to change it. These four values are what IS 456 checks against your district's exposure class."
    >
      <Panel className="divide-y divide-white/[0.07] p-2">
        <SpecRow
          label={t('Concrete grade')}
          value={spec.concrete.grade}
          note={t('Characteristic strength')}
          onEdit={() => {
            setEditor('grade');
          }}
        />
        <SpecRow
          label={t('Cement content')}
          value={`${String(spec.concrete.cement_content_kg_m3)} kg/m³`}
          note={cementLabel}
          onEdit={() => {
            setEditor('cement');
          }}
        />
        <SpecRow
          label={t('Water / cement ratio')}
          value={spec.concrete.water_cement_ratio.toFixed(2)}
          note={t('Lower is denser and more durable')}
          onEdit={() => {
            setEditor('ratio');
          }}
        />
        <SpecRow
          label={t('Walling')}
          value={wallingLabel}
          note={t("Checked for this climate’s suitability")}
          onEdit={() => {
            setEditor('walling');
          }}
        />
      </Panel>

      <div className="mt-10 flex items-center justify-between">
        <Button
          variant="ghost"
          onClick={() => {
            void navigate('/mode');
          }}
        >
          <span aria-hidden="true">←</span> {t('Back')}
        </Button>
        <Button
          onClick={() => {
            void navigate('/score');
          }}
        >
          {t('Score this specification')} <span aria-hidden="true">→</span>
        </Button>
      </div>

      <Popup
        open={editor === 'grade'}
        title={t('Concrete grade')}
        description={t('The characteristic compressive strength in N/mm² at 28 days.')}
        onClose={close}
      >
        <VoiceExplainer
          text={buildNarration(TA.grade.question, TA.grade.options)}
          enabled={voice.enabled}
          className="mb-4"
        />
        <div className="grid grid-cols-3 gap-2 sm:grid-cols-4">
          {CONCRETE_GRADES.map((grade) => (
            <button
              key={grade}
              type="button"
              onClick={() => {
                updateConcrete({ grade });
                close();
              }}
              className={`btn-3d tabular rounded-lg border py-3 text-sm font-semibold ${
                spec.concrete.grade === grade
                  ? 'border-atmos/60 bg-atmos/15 text-atmos'
                  : 'border-white/10 bg-white/[0.03] text-ink-1'
              }`}
            >
              {grade}
            </button>
          ))}
        </div>
        <p className="mt-4 text-xs leading-relaxed text-ink-3">
          {language === 'ta' ? 'கடுமையான வெளிப்பாட்டு வகை குறைந்தபட்ச தரத்தை உயர்த்தும். அதைவிடக் குறைவானதைத் தேர்ந்தெடுப்பது இங்கு பிழையல்ல; மதிப்பீட்டில் குறைபாடாகவும் அதற்கான விதிமுறைப் பிரிவுடனும் காட்டப்படும்.' : 'A severe exposure class raises the minimum grade. Choosing below it is not an error here — it will simply show as a shortfall on your score, with the clause that requires more.'}
        </p>
      </Popup>

      <Popup
        open={editor === 'cement'}
        title={t('Cement')}
        description={language === 'ta' ? 'ஒரு கன மீட்டருக்கான அளவும் சிமெண்டு வகையும்.' : 'Content per cubic metre, and the type.'}
        onClose={close}
      >
        <VoiceExplainer
          text={buildNarration(TA.cement.question, TA.cement.options)}
          enabled={voice.enabled}
          className="mb-4"
        />
        <Field label={t('Cement content')} hint={language === 'ta' ? 'ஒரு கன மீட்டர் கான்கிரீட்டுக்கான கிலோகிராம். வழக்கமாக 250–450.' : 'kg per m³ of concrete. Typically 250–450.'}>
          {(id) => (
            <input
              id={id}
              type="number"
              min={100}
              max={800}
              step={10}
              className={`${CONTROL} tabular`}
              value={spec.concrete.cement_content_kg_m3}
              onChange={(event) => {
                const parsed = Number(event.target.value);
                // A blank or non-numeric field parses to NaN, which would be sent
                // to the API and rejected. Ignoring it keeps the last good value.
                if (!Number.isNaN(parsed)) {
                  updateConcrete({ cement_content_kg_m3: parsed });
                }
              }}
            />
          )}
        </Field>

        <div className="mt-5 space-y-2">
          <p className="text-sm font-medium text-ink-1">{t('Cement type')}</p>
          {CEMENT_TYPES.map((type) => (
            <ChoiceCard
              key={type.value}
              label={type.label}
              hint={
                type.value === 'OPC'
                  ? language === 'ta' ? 'இயல்புநிலை. கூடுதல் கலப்புப் பொருள் இல்லை.' : 'The default. No supplementary material.'
                  : language === 'ta' ? 'கலப்பு சிமெண்டு — குளோரைடு மற்றும் சல்பேட் தாக்கங்களுக்கு பொதுவாகச் சிறந்தது.' : 'Blended — generally better against chlorides and sulphates.'
              }
              selected={spec.concrete.cement_type === type.value}
              onSelect={() => {
                updateConcrete({ cement_type: type.value });
              }}
            />
          ))}
        </div>

        <div className="mt-5 flex justify-end">
          <Button onClick={close}>{t('Done')}</Button>
        </div>
      </Popup>

      <Popup
        open={editor === 'ratio'}
        title={t('Water / cement ratio')}
        description={language === 'ta' ? 'நீரின் நிறை ÷ சிமெண்டின் நிறை.' : 'Mass of water divided by mass of cement.'}
        onClose={close}
      >
        <VoiceExplainer
          text={buildNarration(TA.waterCement.question, TA.waterCement.options)}
          enabled={voice.enabled}
          className="mb-4"
        />
        <div className="tabular text-center text-5xl font-semibold text-atmos">
          {spec.concrete.water_cement_ratio.toFixed(2)}
        </div>
        <input
          type="range"
          min={0.3}
          max={0.7}
          step={0.01}
          aria-label={t('Water to cement ratio')}
          className="mt-6 w-full accent-[var(--color-atmos)]"
          value={spec.concrete.water_cement_ratio}
          onChange={(event) => {
            updateConcrete({ water_cement_ratio: Number(event.target.value) });
          }}
        />
        <div className="tabular mt-1 flex justify-between text-xs text-ink-3">
          <span>{language === 'ta' ? '0.30 — அடர்த்தியானது, கையாளக் கடினம்' : '0.30 — dense, hard to place'}</span>
          <span>{language === 'ta' ? '0.70 — எளிதில் கையாளலாம், துளைகள் அதிகம்' : '0.70 — workable, porous'}</span>
        </div>
        <p className="mt-5 text-xs leading-relaxed text-ink-3">
          {language === 'ta' ? 'நீடித்த தன்மையை நிர்ணயிக்கும் மிக முக்கியமான காரணி இதுவே. அதிகப்படியான நீர் ஆவியாகும்போது நுண்துளைகளை விடுகிறது; அவற்றின் வழியாக ஈரமும் குளோரைடும் கம்பிவலையை அடைகின்றன. அதனால்தான் IS 456 ஒவ்வொரு வெளிப்பாட்டு வகைக்கும் இதன் அதிகபட்ச அளவை நிர்ணயிக்கிறது.' : 'This is the single strongest lever on durability. Excess water leaves capillary pores behind when it evaporates, and those pores are the route moisture and chlorides take to the reinforcement. IS 456 caps it per exposure class for exactly that reason.'}
        </p>
        <div className="mt-5 flex justify-end">
          <Button onClick={close}>{t('Done')}</Button>
        </div>
      </Popup>

      <Popup
        open={editor === 'walling'}
        title={t('Walling material')}
        description={language === 'ta' ? 'உங்கள் மாவட்டத்தின் காலநிலைக்கான பொருத்தம் மதிப்பிடப்படும்.' : "Assessed for suitability in your district's climate."}
        onClose={close}
      >
        <VoiceExplainer
          text={buildNarration(TA.walling.question, TA.walling.options)}
          enabled={voice.enabled}
          className="mb-4"
        />
        <div className="space-y-2">
          {WALLING_MATERIALS.map((material) => (
            <ChoiceCard
              key={material.value}
              label={material.label}
              hint={language === 'ta' ? (WALLING_NOTE_TA[material.value] ?? '') : (WALLING_NOTE[material.value] ?? '')}
              selected={spec.wallingMaterialId === material.value}
              onSelect={() => {
                update({ wallingMaterialId: material.value });
                close();
              }}
            />
          ))}
        </div>
      </Popup>
    </PageShell>
  );
}

/**
 * One line about each walling option, from the reference tables the rules engine
 * uses. Kept short deliberately — the full assessment appears on the score page,
 * where it is backed by the district's actual climate rather than a generalisation.
 */
const WALLING_NOTE: Record<string, string> = {
  burnt_clay_brick: 'The regional default. Absorbs more water than the alternatives.',
  fly_ash_brick: 'Denser and more dimensionally stable than burnt clay.',
  aac_block: 'Light and insulating, but needs protection from driving rain.',
  concrete_solid_block: 'Strong and low-absorption. Poor insulator.',
  engineering_brick: 'Very low absorption. The choice for severe exposure.',
};
const WALLING_NOTE_TA: Record<string, string> = {
  burnt_clay_brick: 'பிராந்தியத்தில் பொதுவாகப் பயன்படுத்துவது. மாற்றுப் பொருட்களைவிட அதிக நீரை உறிஞ்சும்.',
  fly_ash_brick: 'சுட்ட செங்கல்லைவிட அடர்த்தியும் பரிமாண நிலைத்தன்மையும் அதிகம்.',
  aac_block: 'எடை குறைவு, வெப்பத் தடுப்பு உண்டு; நேரடி மழையிலிருந்து பாதுகாப்பு தேவை.',
  concrete_solid_block: 'வலிமையானது, நீர் உறிஞ்சுதல் குறைவு; வெப்பத் தடுப்பு குறைவு.',
  engineering_brick: 'மிகக் குறைந்த நீர் உறிஞ்சுதல். கடுமையான தாக்கத்திற்கான தேர்வு.',
};

function SpecRow({
  label,
  value,
  note,
  onEdit,
}: {
  label: string;
  value: string;
  note: string;
  onEdit: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onEdit}
      className="flex w-full items-center justify-between gap-4 rounded-xl px-4 py-4 text-left transition-colors hover:bg-white/[0.04]"
    >
      <span className="min-w-0">
        <span className="block text-sm font-medium text-ink-1">{label}</span>
        <span className="block truncate text-xs text-ink-3">{note}</span>
      </span>
      <span className="flex shrink-0 items-center gap-2.5">
        <span className="tabular text-base font-semibold text-atmos">{value}</span>
        <span aria-hidden="true" className="text-ink-3">
          ›
        </span>
      </span>
    </button>
  );
}
