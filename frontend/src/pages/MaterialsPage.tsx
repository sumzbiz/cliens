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
import {
  Button,
  CONTROL,
  CheckBadge,
  ChoiceCard,
  ErrorNotice,
  Field,
  Panel,
  Popup,
  RequirementsSummary,
  Spinner,
} from '@/components/ui';
import { gradeLabel, useSiteRequirements } from '@/hooks/useSiteRequirements';
import { useSession } from '@/state/session-context';
import { CEMENT_TYPES, CONCRETE_GRADES, WALLING_MATERIALS } from '@/types/api';

/** Which popup is open, if any. */
type Editor = 'grade' | 'cement' | 'ratio' | 'walling' | null;

/**
 * Accepted cement content, kg/m³. The API rejects anything above 800, and below
 * 100 is not a structural concrete; IS 456 minimums start at 300.
 */
const CEMENT_MIN_KG_M3 = 100;
const CEMENT_MAX_KG_M3 = 800;

export default function MaterialsPage() {
  const { spec, area, update, updateConcrete } = useSession();
  const navigate = useNavigate();
  const [editor, setEditor] = useState<Editor>(null);
  const voice = useVoice();
  const site = useSiteRequirements(spec.district, area, spec.situation);
  // The field's text is kept separately from the committed value, so typing
  // "3" on the way to "340" is not rejected or sent mid-keystroke.
  const [cementDraft, setCementDraft] = useState(String(spec.concrete.cement_content_kg_m3));
  const cementValue = Number(cementDraft);
  const cementValid =
    cementDraft.trim() !== '' &&
    Number.isFinite(cementValue) &&
    cementValue >= CEMENT_MIN_KG_M3 &&
    cementValue <= CEMENT_MAX_KG_M3;

  const close = () => {
    setEditor(null);
  };

  const requirements = site.status === 'ready' ? site.requirements : null;
  const gradeMpa = Number(spec.concrete.grade.slice(1));

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
      lead="Tap any line to change it. Each value is checked live against what IS 456 requires at your site."
    >
      <Panel className="mb-4 p-5">
        {site.status === 'loading' && <Spinner label="Checking what this site needs…" />}
        {site.status === 'error' && <ErrorNotice error={site.error} />}
        {requirements !== null && (
          <RequirementsSummary
            exposureLabel={requirements.exposureLabel}
            minGrade={gradeLabel(requirements.minGradeMpa)}
            minCementKgM3={requirements.minCementKgM3}
            maxWaterCementRatio={requirements.maxWaterCementRatio}
          />
        )}
      </Panel>

      <Panel className="divide-y divide-white/[0.07] p-2">
        <SpecRow
          label="Concrete grade"
          value={spec.concrete.grade}
          note={
            requirements === null
              ? 'Characteristic strength'
              : `Needs at least ${gradeLabel(requirements.minGradeMpa)}`
          }
          ok={requirements === null ? null : gradeMpa >= requirements.minGradeMpa}
          onEdit={() => {
            setEditor('grade');
          }}
        />
        <SpecRow
          label="Cement content"
          value={`${String(spec.concrete.cement_content_kg_m3)} kg/m³`}
          note={
            requirements === null
              ? cementLabel
              : `${cementLabel} · needs at least ${requirements.minCementKgM3.toFixed(0)} kg/m³`
          }
          ok={
            requirements === null
              ? null
              : spec.concrete.cement_content_kg_m3 >= requirements.minCementKgM3
          }
          onEdit={() => {
            setCementDraft(String(spec.concrete.cement_content_kg_m3));
            setEditor('cement');
          }}
        />
        <SpecRow
          label="Water / cement ratio"
          value={spec.concrete.water_cement_ratio.toFixed(2)}
          note={
            requirements === null
              ? 'Lower is denser and more durable'
              : `Must not exceed ${requirements.maxWaterCementRatio.toFixed(2)}`
          }
          ok={
            requirements === null
              ? null
              : spec.concrete.water_cement_ratio <= requirements.maxWaterCementRatio
          }
          onEdit={() => {
            setEditor('ratio');
          }}
        />
        <SpecRow
          label="Walling"
          value={wallingLabel}
          note="Checked for this climate's suitability"
          ok={null}
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
          <span aria-hidden="true">←</span> Back
        </Button>
        <Button
          onClick={() => {
            void navigate('/score');
          }}
        >
          Score this specification <span aria-hidden="true">→</span>
        </Button>
      </div>

      <Popup
        open={editor === 'grade'}
        title="Concrete grade"
        description="The characteristic compressive strength in N/mm² at 28 days."
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
          A severe exposure class raises the minimum grade. Choosing below it is not an error here —
          it will simply show as a shortfall on your score, with the clause that requires more.
        </p>
      </Popup>

      <Popup
        open={editor === 'cement'}
        title="Cement"
        description="Content per cubic metre, and the type."
        onClose={close}
      >
        <VoiceExplainer
          text={buildNarration(TA.cement.question, TA.cement.options)}
          enabled={voice.enabled}
          className="mb-4"
        />
        <Field
          label="Cement content"
          hint={
            requirements === null
              ? 'kg per m³ of concrete. Typically 300–450.'
              : `kg per m³ of concrete. Your site needs at least ${requirements.minCementKgM3.toFixed(0)}.`
          }
        >
          {(id) => (
            <>
              <input
                id={id}
                type="number"
                inputMode="numeric"
                min={CEMENT_MIN_KG_M3}
                max={CEMENT_MAX_KG_M3}
                step={10}
                aria-invalid={!cementValid}
                aria-describedby={cementValid ? undefined : `${id}-error`}
                className={`${CONTROL} tabular ${cementValid ? '' : 'border-band-poor/70'}`}
                value={cementDraft}
                onChange={(event) => {
                  const text = event.target.value;
                  setCementDraft(text);
                  const parsed = Number(text);
                  // Only an in-range number is committed. Anything else stays in
                  // the field with an error, rather than being sent to the API
                  // and rejected there, or silently replaced.
                  if (
                    text.trim() !== '' &&
                    parsed >= CEMENT_MIN_KG_M3 &&
                    parsed <= CEMENT_MAX_KG_M3
                  ) {
                    updateConcrete({ cement_content_kg_m3: parsed });
                  }
                }}
              />
              {!cementValid && (
                <p id={`${id}-error`} role="alert" className="mt-1.5 text-xs text-band-poor">
                  Enter a value between {CEMENT_MIN_KG_M3} and {CEMENT_MAX_KG_M3} kg/m³.
                </p>
              )}
            </>
          )}
        </Field>

        <div className="mt-5 space-y-2">
          <p className="text-sm font-medium text-ink-1">Cement type</p>
          {CEMENT_TYPES.map((type) => (
            <ChoiceCard
              key={type.value}
              label={type.label}
              hint={
                type.value === 'OPC'
                  ? 'The default. No supplementary material.'
                  : 'Blended — generally better against chlorides and sulphates.'
              }
              selected={spec.concrete.cement_type === type.value}
              onSelect={() => {
                updateConcrete({ cement_type: type.value });
              }}
            />
          ))}
        </div>

        <div className="mt-5 flex justify-end">
          <Button onClick={close} disabled={!cementValid}>
            Done
          </Button>
        </div>
      </Popup>

      <Popup
        open={editor === 'ratio'}
        title="Water / cement ratio"
        description="Mass of water divided by mass of cement."
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
          aria-label="Water to cement ratio"
          className="mt-6 w-full accent-[var(--color-atmos)]"
          value={spec.concrete.water_cement_ratio}
          onChange={(event) => {
            updateConcrete({ water_cement_ratio: Number(event.target.value) });
          }}
        />
        <div className="tabular mt-1 flex justify-between text-xs text-ink-3">
          <span>0.30 — dense, hard to place</span>
          <span>0.70 — workable, porous</span>
        </div>
        {requirements !== null && (
          <p className="mt-3 flex items-center justify-center gap-2 text-sm text-ink-2">
            Your site allows at most{' '}
            <span className="tabular font-semibold text-ink-1">
              {requirements.maxWaterCementRatio.toFixed(2)}
            </span>
            <CheckBadge ok={spec.concrete.water_cement_ratio <= requirements.maxWaterCementRatio} />
          </p>
        )}
        <p className="mt-5 text-xs leading-relaxed text-ink-3">
          This is the single strongest lever on durability. Excess water leaves capillary pores
          behind when it evaporates, and those pores are the route moisture and chlorides take to
          the reinforcement. IS 456 caps it per exposure class for exactly that reason.
        </p>
        <div className="mt-5 flex justify-end">
          <Button onClick={close}>Done</Button>
        </div>
      </Popup>

      <Popup
        open={editor === 'walling'}
        title="Walling material"
        description="Assessed for suitability in your district's climate."
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
              hint={WALLING_NOTE[material.value] ?? ''}
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

function SpecRow({
  label,
  value,
  note,
  ok,
  onEdit,
}: {
  label: string;
  value: string;
  note: string;
  /** Whether the value clears the site's limit; null when there is no limit to show. */
  ok: boolean | null;
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
        {ok !== null && <CheckBadge ok={ok} />}
        <span className="tabular text-base font-semibold text-atmos">{value}</span>
        <span aria-hidden="true" className="text-ink-3">
          ›
        </span>
      </span>
    </button>
  );
}
