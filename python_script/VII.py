"""
polyphony rnn model.

VERSION: Magenta 2.0.1
"""

import math
import os
import time
from typing import Generator

import magenta.music as mm
import tensorflow as tf
from magenta.models.polyphony_rnn import polyphony_sequence_generator
from magenta.models.shared import sequence_generator_bundle
from magenta.music import DEFAULT_QUARTERS_PER_MINUTE
from magenta.protobuf.generator_pb2 import GeneratorOptions
from magenta.protobuf.music_pb2 import NoteSequence
# from visual_midi import Plotter


def generate(bundle_name: str,
             sequence_generator,
             generator_id: str,
             midi_filename: str,
             total_length_steps: int,
             steps_per_quarter: int,
             primer_filename: str = None,
             qpm: float = DEFAULT_QUARTERS_PER_MINUTE,
             condition_on_primer: bool = False,
             inject_primer_during_generation: bool = False,
             temperature: float = 1.0,
             beam_size: int = 1,
             branch_factor: int = 1,
             steps_per_iteration: int = 1) -> NoteSequence:
  """Generates and returns a new sequence given the sequence generator.

  Uses the bundle name to download the bundle in the "bundles" directory if it
  doesn't already exist, then uses the sequence generator and the generator id
  to get the generator. Parameters can be provided for the generation phase.
  The MIDI and plot files are written to disk in the "output" folder, with the
  filename pattern "<generator_name>_<generator_id>_<date_time>" with "mid" or
  "html" as extension respectively.

      :param bundle_name: The bundle name to be downloaded and generated with.

      :param sequence_generator: The sequence generator module, which is the
      python module in the corresponding models subfolder.

      :param generator_id: The id of the generator configuration, this is the
      model's configuration.

      :param primer_filename: The filename for the primer, which will be taken
      from the "primers" directory. If left empty, and empty note sequence will
      be used.

      :param qpm: The QPM for the generated sequence. If a primer is provided,
      the primer QPM will be used and this parameter ignored.

      :param condition_on_primer: Activates the primer conditioning, which will
      use the primer to establish a certain key before the generation starts.

      :param inject_primer_during_generation: Activates the primer injection,
      which will inject the primer in the generated sequence.

      :param total_length_steps: The total length of the sequence, which contains
      the added length of the primer and the generated sequence together. This
      value need to be bigger than the primer length in bars.

      :param temperature: The temperature value for the generation algorithm,
      lesser than 1 is less random (closer to the primer), bigger than 1 is
      more random

      :param beam_size: The beam size for the generation algorithm, a bigger
      branch size means the generation algorithm will generate more sequence
      each iteration, meaning a less random sequence at the cost of more time.

      :param branch_factor: The branch factor for the generation algorithm,
      a bigger branch factor means the generation algorithm will keep more
      sequence candidates at each iteration, meaning a less random sequence
      at the cost of more time.

      :param steps_per_iteration: The number of steps the generation algorithm
      generates at each iteration, a bigger steps per iteration meaning there
      are less iterations in total because more steps gets generated each time.


      :returns The generated NoteSequence
  """

  # Downloads the bundle from the magenta website, a bundle (.mag file) is a
  # trained model that is used by magenta
  mm.notebook_utils.download_bundle(bundle_name, "bundles")
  bundle = sequence_generator_bundle.read_bundle_file(
    os.path.join("bundles", bundle_name))

  # Initialize the generator from the generator id, this need to fit the
  # bundle we downloaded before, and choose the model's configuration.
  generator_map = sequence_generator.get_generator_map()
  generator = generator_map[generator_id](checkpoint=None, bundle=bundle)
  generator.initialize()

  steps_per_quarter 

  setattr(generator, "steps_per_quarter", steps_per_quarter)

  # Gets the primer sequence that is fed into the model for the generator,
  # which will generate a sequence based on this one.
  # If no primer sequence is given, the primer sequence is initialized
  # to an empty note sequence
  if primer_filename:
    primer_sequence = mm.midi_io.midi_file_to_note_sequence(
      os.path.join("generated", primer_filename))
  else:
    primer_sequence = NoteSequence()

  # Gets the QPM from the primer sequence. If it wasn't provided, take the
  # parameters that defaults to Magenta's default
  if primer_sequence.tempos:
    if len(primer_sequence.tempos) > 1:
      raise Exception("No support for multiple tempos")
    qpm = primer_sequence.tempos[0].qpm

  # Calculates the seconds per 1 step, which changes depending on the QPM value
  # (steps per quarter in generators are mostly 4)
  seconds_per_step = 60.0 / qpm / getattr(generator, "steps_per_quarter", 4)

  # Calculates the primer sequence length in steps and time by taking the
  # total time (which is the end of the last note) and finding the next step
  # start time.
  primer_sequence_length_steps = math.ceil(primer_sequence.total_time
                                           / seconds_per_step)
  primer_sequence_length_time = primer_sequence_length_steps * seconds_per_step

  # Calculates the start and the end of the primer sequence.
  # We add a negative delta to the end, because if we don't some generators
  # won't start the generation right at the beginning of the bar, they will
  # start at the next step, meaning we'll have a small gap between the primer
  # and the generated sequence.
  primer_end_adjust = (0.00001 if primer_sequence_length_time > 0 else 0)
  primer_start_time = 0
  primer_end_time = (primer_start_time
                     + primer_sequence_length_time
                     - primer_end_adjust)

  # Calculates the generation time by taking the total time and substracting
  # the primer time. The resulting generation time needs to be bigger than zero.
  generation_length_steps = total_length_steps - primer_sequence_length_steps
  if generation_length_steps <= 0:
    raise Exception("Total length in steps too small "
                    + "(" + str(total_length_steps) + ")"
                    + ", needs to be at least one bar bigger than primer "
                    + "(" + str(primer_sequence_length_steps) + ")")
  generation_length_time = generation_length_steps * seconds_per_step

  # Calculates the generate start and end time, the start time will contain
  # the previously added negative delta from the primer end time.
  # We remove the generation end time delta to end the generation
  # on the last bar.
  generation_start_time = primer_end_time
  generation_end_time = (generation_start_time
                         + generation_length_time
                         + primer_end_adjust)

  # Showtime
  print(f"Primer time: [{primer_start_time}, {primer_end_time}]")
  print(f"Generation time: [{generation_start_time}, {generation_end_time}]")

  # Pass the given parameters, the generator options are common for all models,
  # except for condition_on_primer and no_inject_primer_during_generation
  # which are specific to polyphonic models
  generator_options = GeneratorOptions()
  generator_options.args['temperature'].float_value = temperature
  generator_options.args['beam_size'].int_value = beam_size
  generator_options.args['branch_factor'].int_value = branch_factor
  generator_options.args['steps_per_iteration'].int_value = steps_per_iteration
  generator_options.args['condition_on_primer'].bool_value = condition_on_primer
  generator_options.args['no_inject_primer_during_generation'].bool_value = (
    not inject_primer_during_generation)
  generator_options.generate_sections.add(
    start_time=generation_start_time,
    end_time=generation_end_time)

  # Generates the sequence, add add the time signature
  # back to the generated sequence
  sequence = generator.generate(primer_sequence, generator_options)

  # Writes the resulting midi file to the output directory
  # midi_filename = str 
  midi_path = os.path.join("generated", midi_filename)
  mm.midi_io.note_sequence_to_midi_file(sequence, midi_path)
  print(f"Generated midi file: {os.path.abspath(midi_path)}")


  return sequence
	

def app(unused_argv):
  """ Generates 6 sequences, each one used as the primer for the next generation.  The final output is named "generated"."""

bundles = ("angry.mag", "wativ.mag", "wativ.mag", "neutral.mag", "wativ.mag", "duo.mag")
filenames = ["primer.mid", "primer1.mid", "primer2.mid", "primer3.mid", "primer4.mid", "VIII.machine_music_wativ_img_2440_9.mid"]
steps = []
bars = [12, 8, 8, 8, 4, 4]
s_p_q = [4, 16, 32, 32, 6, 2] 
totalBars = 0
for idx, x in enumerate(bars):
    totalBars = totalBars + x
    steps.append(totalBars * s_p_q[idx] * 4)
    print(totalBars)
conditions = [False, False, False, False, FoTheTrue, False]
injections = [True, True, False, True, True, True]
temperatures = [1.0, 1.0, 1.0, 1.0, 1.0, 1.4]
primers = ["wativ_img_2440.mid", "primer.mid", "primer1.mid", "primer2.mid", "primer3.mid", "primer4.mid"]

for x in range (len(bars)): 
      print("x = ", x)
      bundle = bundles[x]
      filename = filenames[x] 
      step = steps[x]
      spq = s_p_q[x]
      condition = conditions[x]
      injection = injections[x]
      temperature = temperatures[x]
      primer = primers[x] 
    

      generate( 
        bundle_name=bundle,
        sequence_generator=polyphony_sequence_generator,
        generator_id="polyphony",
        midi_filename=filename,
        total_length_steps=step, 
        steps_per_quarter=spq,
        condition_on_primer=condition,
        inject_primer_during_generation=injection,
        temperature=temperature,
        primer_filename=primer) 

#   return 0



# if(spq == 1):
# 		step * 4
# if(spq == 2):
#         step * 2
# if(spq == 8):
#         step / 2
# if(spq == 8):
#         step / 4



if __name__ == "__main__":
  tf.compat.v1.disable_v2_behavior()
  tf.compat.v1.app.run(app)